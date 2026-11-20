"""Mutual funds: CAS review / import, AMFI scheme search and prices. Included before the
investments router so /investments/cas and /investments/nav aren't read as an account id."""

from datetime import date as Date
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ..accounts.models import Account
from ..auth.security import current_user
from ..gmail.models import GmailAttachment
from ..transactions.models import Transaction
from ..transactions.service import txn_out
from .cas_service import KIND_LABEL, already_invested, bad, bank_accounts, do_import, refresh, revive
from .models import CasImport, Fund, Investment
from .nav import get_status, search_schemes, update_navs

router = APIRouter(prefix="/investments", tags=["investments"], dependencies=[Depends(current_user)])


class SchemeOut(BaseModel):
    code: str
    isin: str | None
    name: str
    amc: str | None
    nav: int | None  # 1/10000 rupee
    nav_date: Date | None


class NavStatus(BaseModel):
    last_run: str | None = None
    updated: int = 0
    funds: int = 0
    error: str | None = None
    not_found: list[str] = []


class CasFundOut(BaseModel):
    id: int
    amc: str | None
    folio: str | None
    scheme: str
    isin: str | None
    opening_units: int  # milli-units
    closing_units: int | None
    nav: int | None  # 1/10000 rupee
    nav_date: Date | None
    cost: int | None
    market_value: int | None
    account_id: int | None
    account_name: str | None
    skip: bool
    mode: Literal["both", "fund", "txns"]
    rows: int
    already_imported: int  # rows imported before (from an earlier CAS) — skipped
    replaces_opening: int | None  # a fund you added by hand: its "already invested" amount, replaced on import
    units_now: float | None  # the fund it joins: units recorded now


class CasRowOut(BaseModel):
    id: int
    fund_id: int
    date: Date
    description: str
    kind: str
    kind_label: str
    amount: int
    units: int
    nav: int
    balance: int
    stamp_duty: int
    action: str
    match: dict | None  # the matched transaction
    bank_account_id: int | None
    pair_row_id: int | None
    existing: bool
    user_set: bool
    transaction_id: int | None


class CasOut(BaseModel):
    id: int
    filename: str
    period_from: Date | None
    period_to: Date | None
    status: str
    created_at: datetime
    imported_at: datetime | None
    gmail_message_id: str | None
    funds: list[CasFundOut]
    rows: list[CasRowOut]
    unparsed: list[str]
    counts: dict[str, int]


class CasSummary(BaseModel):
    id: int
    filename: str
    period_from: Date | None
    period_to: Date | None
    status: str
    created_at: datetime
    funds: int
    rows: int


class CasFundPatch(BaseModel):
    account_id: int | None = None  # None = a new investment on import
    skip: bool = False  # don't import this fund
    auto: bool = False  # import it again, into the fund suggested for it (or a new one)


class CasFundMode(BaseModel):
    mode: Literal["both", "fund", "txns"]


class CasRowPatch(BaseModel):
    action: Literal["link", "convert", "transfer", "switch", "before", "units", "skip"]
    bank_account_id: int | None = None


class CasBulkIn(BaseModel):
    """The action for every row still without a match that you haven't changed."""

    action: Literal["transfer", "before", "skip"]
    bank_account_id: int | None = None
    before: Date | None = None  # only rows dated before this


# ---------------------------------------------------------------- schemes and prices


@router.get("/schemes", response_model=list[SchemeOut])
def schemes(q: str = "") -> list[SchemeOut]:
    """Search AMFI's scheme list (downloaded once a day) — to add a fund by hand."""
    if len(q.strip()) < 3:
        return []
    try:
        return [SchemeOut(**s) for s in search_schemes(q)]
    except Exception:
        raise bad("Couldn't get the fund list from AMFI. Check the server's internet connection.", "amfi") from None


@router.get("/nav/status", response_model=NavStatus)
def nav_status(db: Session = Depends(get_db)) -> NavStatus:
    return NavStatus(**get_status(db))


@router.post("/nav/refresh", response_model=NavStatus)
def refresh_navs(db: Session = Depends(get_db)) -> NavStatus:
    return NavStatus(**update_navs(db))


# ---------------------------------------------------------------- CAS


def _cas_out(db: Session, cas: CasImport) -> CasOut:
    ids = [f.account_id for f in cas.funds if f.account_id]
    names = {a.id: a.name for a in db.scalars(select(Account).where(Account.id.in_(ids)))} if ids else {}
    per_fund: dict[int, int] = {}
    existing: dict[int, int] = {}
    for r in cas.rows:
        if r.existing:
            existing[r.fund_id] = existing.get(r.fund_id, 0) + 1
    counts = {"rows": len(cas.rows), "existing": 0, "link": 0, "convert": 0, "transfer": 0, "switch": 0}
    counts |= {"before": 0, "units": 0, "skip": 0}
    rows = []
    for r in cas.rows:
        per_fund[r.fund_id] = per_fund.get(r.fund_id, 0) + 1
        counts["existing" if r.existing else r.action] = counts.get("existing" if r.existing else r.action, 0) + 1
        m = db.get(Transaction, r.match_transaction_id) if r.match_transaction_id else None
        rows.append(
            CasRowOut(
                id=r.id,
                fund_id=r.fund_id,
                date=r.date,
                description=r.description,
                kind=r.kind,
                kind_label=KIND_LABEL.get(r.kind, r.kind),
                amount=r.amount,
                units=r.units,
                nav=r.nav,
                balance=r.balance,
                stamp_duty=r.stamp_duty,
                action=r.action,
                match=txn_out(m).model_dump(mode="json") if m else None,
                bank_account_id=r.bank_account_id,
                pair_row_id=r.pair_row_id,
                existing=r.existing,
                user_set=r.user_set,
                transaction_id=r.transaction_id,
            )
        )
    att = db.get(GmailAttachment, cas.attachment_id) if cas.attachment_id else None
    return CasOut(
        id=cas.id,
        filename=cas.filename,
        period_from=cas.period_from,
        period_to=cas.period_to,
        status=cas.status,
        created_at=cas.created_at,
        imported_at=cas.imported_at,
        gmail_message_id=att.message_id if att else None,
        funds=[
            CasFundOut(
                id=f.id,
                amc=f.amc,
                folio=f.folio,
                scheme=f.scheme,
                isin=f.isin,
                opening_units=f.opening_units,
                closing_units=f.closing_units,
                nav=f.nav,
                nav_date=f.nav_date,
                cost=f.cost,
                market_value=f.market_value,
                account_id=f.account_id,
                account_name=names.get(f.account_id) if f.account_id else None,
                skip=f.skip,
                mode=f.mode,  # type: ignore[arg-type]
                rows=per_fund.get(f.id, 0),
                already_imported=existing.get(f.id, 0),
                replaces_opening=(
                    already_invested(db, f.account_id)
                    if not f.skip
                    and f.mode != "fund"
                    and any(r.fund_id == f.id and r.action == "before" for r in cas.rows)
                    else None
                ),
                units_now=(fund.units / 1000 if (fund := db.get(Fund, f.account_id or -1)) else None),
            )
            for f in cas.funds
        ],
        rows=rows,
        unparsed=cas.unparsed or [],
        counts=counts,
    )


def _get(db: Session, cid: int) -> CasImport:
    cas = db.get(CasImport, cid)
    if cas is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "CAS not found")
    return cas


def _draft(db: Session, cid: int) -> CasImport:
    cas = _get(db, cid)
    if cas.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, "This CAS is already imported.")
    return cas


@router.get("/cas", response_model=list[CasSummary])
def list_cas(db: Session = Depends(get_db)) -> list[CasSummary]:
    return [
        CasSummary(
            id=c.id,
            filename=c.filename,
            period_from=c.period_from,
            period_to=c.period_to,
            status=c.status,
            created_at=c.created_at,
            funds=len(c.funds),
            rows=len(c.rows),
        )
        for c in db.scalars(select(CasImport).order_by(CasImport.id.desc()).limit(50))
    ]


@router.get("/cas/{cid}", response_model=CasOut)
def get_cas(cid: int, db: Session = Depends(get_db)) -> CasOut:
    cas = _get(db, cid)
    if revive(db, cas):  # its funds were deleted since it was imported
        db.commit()
    elif cas.status == "draft":
        refresh(db, cas)  # transactions may have changed since it was read
        db.commit()
    return _cas_out(db, cas)


@router.patch("/cas/{cid}/funds/{fid}", response_model=CasOut)
def set_fund_account(cid: int, fid: int, body: CasFundPatch, db: Session = Depends(get_db)) -> CasOut:
    cas = _draft(db, cid)
    f = next((x for x in cas.funds if x.id == fid), None)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fund not found")
    if body.account_id is not None and not body.skip:
        inv = db.scalar(select(Investment).where(Investment.account_id == body.account_id))
        if inv is None or inv.kind != "mf":
            raise bad("Pick one of your mutual funds, or a new one.")
        if any(x.id != fid and x.account_id == body.account_id and not x.skip for x in cas.funds):
            raise bad("Another fund in this CAS already goes there — each fund needs its own.")
    f.skip = body.skip
    f.account_id = None if body.skip else body.account_id
    f.create_new = not body.skip and body.account_id is None and not body.auto
    if f.mode == "txns" and f.create_new:
        f.mode = "both"  # a new fund needs its details: "transactions only" is for one you have
    for r in cas.rows:
        if r.fund_id == fid:
            r.user_set = False  # matches depend on the account: work them out again
    refresh(db, cas)
    db.commit()
    return _cas_out(db, cas)


@router.patch("/cas/{cid}/funds/{fid}/mode", response_model=CasOut)
def set_fund_mode(cid: int, fid: int, body: CasFundMode, db: Session = Depends(get_db)) -> CasOut:
    """Import the fund and its transactions, the fund only (today's holding), or the transactions only."""
    cas = _draft(db, cid)
    f = next((x for x in cas.funds if x.id == fid), None)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fund not found")
    if body.mode == "txns" and (f.skip or f.account_id is None or db.get(Fund, f.account_id) is None):
        raise bad("“Transactions only” adds rows to a fund you already have — pick it under “Goes to” first.")
    f.mode = body.mode
    if f.skip:
        f.skip = False
        refresh(db, cas)
    db.commit()
    return _cas_out(db, cas)


@router.patch("/cas/{cid}/rows/{rid}", response_model=CasOut)
def set_row(cid: int, rid: int, body: CasRowPatch, db: Session = Depends(get_db)) -> CasOut:
    cas = _draft(db, cid)
    r = next((x for x in cas.rows if x.id == rid), None)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Row not found")
    if r.fund.skip and body.action != "skip":
        raise bad("This fund is set to “Don't import” — choose where it goes first.")
    if body.action in ("link", "convert") and r.match_transaction_id is None:
        raise bad("There's no matching transaction for this row.")
    if body.action == "switch" and not r.pair_row_id:
        raise bad("This row isn't one side of a switch.")
    if body.action == "transfer":
        bank = body.bank_account_id or r.bank_account_id
        if bank is None or bank not in {a.id for a in bank_accounts(db)}:
            raise bad("Choose the bank or cash account the money went from / to.")
        r.bank_account_id = bank
    r.action = body.action
    r.user_set = True
    db.commit()
    return _cas_out(db, cas)


@router.post("/cas/{cid}/bulk", response_model=CasOut)
def bulk(cid: int, body: CasBulkIn, db: Session = Depends(get_db)) -> CasOut:
    cas = _draft(db, cid)
    if body.action == "transfer" and body.bank_account_id not in {a.id for a in bank_accounts(db)}:
        raise bad("Choose the bank or cash account.")
    for r in cas.rows:
        if r.existing or r.user_set or r.action not in ("transfer", "before"):
            continue
        if body.before and r.date >= body.before:
            continue
        r.action = body.action
        if body.action == "transfer":
            r.bank_account_id = body.bank_account_id
    db.commit()
    return _cas_out(db, cas)


@router.post("/cas/{cid}/import")
def import_cas(cid: int, db: Session = Depends(get_db)) -> dict:
    cas = _get(db, cid)
    result = do_import(db, cas)
    return {"cas": _cas_out(db, cas).model_dump(mode="json"), **result}


@router.delete("/cas/{cid}", status_code=204)
def discard_cas(cid: int, db: Session = Depends(get_db)) -> None:
    db.delete(_get(db, cid))
    db.commit()

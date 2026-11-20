"""CAS drafts -> review suggestions -> import (ported from the old build, reviewed).

A fund is an investment account (kind "mf") whose ledger balance is the money put in
(net of redemptions); units and NAV live on `Fund`. Every CAS row becomes a `FundTxn`
(the units side). The money side is an ordinary transaction: matched to one you already
have (the SIP transfer), converted from a matching bank expense, created, or counted in
the opening balance for history older than your records.
"""

import re
from collections import Counter
from datetime import date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..accounts.models import Account, AccountType
from ..transactions.models import Transaction, TransactionType
from ..transactions.schemas import TransactionIn
from ..transactions.service import apply_body
from .cas import CasStatement, consistency, is_cas, parse_cas
from .models import CasFund, CasImport, CasRow, Fund, FundTxn, Investment

BANK_TYPES = ("asset", "cash")
KIND_LABEL = {
    "purchase": "Purchase",
    "sip": "SIP",
    "redemption": "Redemption",
    "switch_in": "Switch in",
    "switch_out": "Switch out",
    "dividend_reinvest": "Dividend reinvested",
    "dividend_payout": "Dividend paid",
    "reversal": "Reversal",
}


def bad(msg: str, code: str = "invalid") -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": code, "message": msg})


def best_reading(candidates: list[tuple[str, str]]) -> tuple[str, CasStatement] | None:
    """Of the PDF's text extractions, the one whose unit balances add up best."""
    best = None
    for _method, text in candidates:
        if not is_cas(text):
            continue
        st = parse_cas(text)
        sc = (consistency(st), sum(len(f.txns) for f in st.funds), len(st.funds))
        if best is None or sc > best[0]:
            best = (sc, text, st)
    return (best[1], best[2]) if best else None


def bank_accounts(db: Session) -> list[Account]:
    return list(db.scalars(select(Account).where(Account.type.in_(BANK_TYPES)).order_by(Account.id)))


def records_start(db: Session, ids: list[int]) -> date | None:
    """The first date your bank / cash accounts have transactions: CAS rows before it are older history."""
    if not ids:
        return None
    return db.scalar(
        select(func.min(Transaction.date)).where(
            or_(Transaction.source_id.in_(ids), Transaction.destination_id.in_(ids))
        )
    )


def _folio(s: str | None) -> str:
    return re.sub(r"\W", "", s or "").lower()


def _suggest_account(db: Session, f: CasFund, taken: set[int]) -> int | None:
    """A mutual fund you already have for this CAS fund: same ISIN (and a folio that doesn't
    differ), else same folio and name, else the same name — so it isn't added twice."""
    funds = [x for x in db.scalars(select(Fund)) if x.account_id not in taken]
    folio = _folio(f.folio)
    for x in funds:
        if f.isin and x.isin == f.isin and (not folio or not x.folio or _folio(x.folio) == folio):
            return x.account_id
    name = f.scheme.strip().lower()
    for x in funds:
        same_name = x.scheme.strip().lower() == name
        if same_name and (not x.isin or not f.isin) and (not folio or not x.folio or _folio(x.folio) == folio):
            return x.account_id
    return None


def already_invested(db: Session, account_id: int | None) -> int | None:
    """The "already invested" amount of a fund you added by hand (no CAS rows yet): the
    CAS's older purchases replace it on import, so it isn't counted twice."""
    if not account_id or db.scalar(select(FundTxn.id).where(FundTxn.account_id == account_id).limit(1)):
        return None
    acct = db.get(Account, account_id)
    return acct.opening_balance if acct is not None and acct.opening_balance > 0 else None


def used_transactions(db: Session) -> set[int]:
    """Transactions already recording the money of an imported CAS row."""
    return set(db.scalars(select(FundTxn.transaction_id).where(FundTxn.transaction_id.is_not(None))))


def _match(db: Session, row: CasRow, fund_acct: int | None, own_ids: list[int], claimed: set[int]):
    """An existing transaction for this row's money: ("link", id) when it's already a transfer
    with this fund, ("convert", id) for a bank expense / income that should become one."""
    gross = row.amount + row.stamp_duty if row.amount > 0 else row.amount
    amounts = {abs(gross), abs(row.amount)}
    if row.amount > 0:  # bank -> fund: debited on the day or a few days before
        lo, hi = row.date - timedelta(days=5), row.date + timedelta(days=2)
    else:  # redemption: credited a few days after
        lo, hi = row.date - timedelta(days=1), row.date + timedelta(days=7)
    base = select(Transaction).where(Transaction.amount.in_(amounts), Transaction.date >= lo, Transaction.date <= hi)

    def best(rows):
        rows = [t for t in rows if t.id not in claimed]
        return min(rows, key=lambda t: abs((t.date - row.date).days)) if rows else None

    if fund_acct is not None:
        side = Transaction.destination_id if row.amount > 0 else Transaction.source_id
        t = best(db.scalars(base.where(Transaction.type == TransactionType.transfer.value, side == fund_acct)).unique())
        if t:
            return "link", t.id
    if own_ids:
        if row.amount > 0:
            q = base.where(Transaction.type == TransactionType.withdrawal.value, Transaction.source_id.in_(own_ids))
        else:
            q = base.where(Transaction.type == TransactionType.deposit.value, Transaction.destination_id.in_(own_ids))
        t = best(db.scalars(q).unique())
        if t:
            return "convert", t.id
    return None


def _busiest(db: Session, ids: list[int]) -> int | None:
    counts = {
        i: db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(or_(Transaction.source_id == i, Transaction.destination_id == i))
        )
        or 0
        for i in ids
    }
    return max(counts, key=lambda k: counts[k]) if counts else None


def refresh(db: Session, cas: CasImport) -> None:
    """(Re)work out fund accounts, rows already imported, matches and the action of every
    row you haven't changed."""
    taken = {f.account_id for f in cas.funds if f.account_id}
    for f in cas.funds:
        if f.account_id is None and not f.create_new and not f.skip:
            f.account_id = _suggest_account(db, f, taken)
            if f.account_id:
                taken.add(f.account_id)
    by_fund = {f.id: f for f in cas.funds}
    own_ids = [a.id for a in bank_accounts(db)]
    start = records_start(db, own_ids)
    claimed = {r.match_transaction_id for r in cas.rows if r.user_set and r.match_transaction_id}
    claimed |= used_transactions(db)  # one bank payment records one CAS row, across all CAS files
    bank_votes: Counter = Counter()

    # switches: pair an "out" with an "in" of the same amount within 3 days
    for r in cas.rows:
        r.pair_row_id = None
    skipped = {f.id for f in cas.funds if f.skip}
    outs = [r for r in cas.rows if r.kind == "switch_out" and r.fund_id not in skipped]
    ins = [r for r in cas.rows if r.kind == "switch_in" and r.fund_id not in skipped]
    for o in outs:
        p = next(
            (
                i
                for i in ins
                if i.pair_row_id is None
                and abs(i.amount) == abs(o.amount)
                and abs((i.date - o.date).days) <= 3
                and i.fund_id != o.fund_id
            ),
            None,
        )
        if p:
            o.pair_row_id, p.pair_row_id = p.id, o.id

    for r in cas.rows:
        f = by_fund[r.fund_id]
        if f.skip:
            r.existing, r.action, r.match_transaction_id, r.user_set = False, "skip", None, False
            continue
        r.existing = bool(
            f.account_id
            and db.scalar(
                select(FundTxn.id).where(
                    FundTxn.account_id == f.account_id,
                    FundTxn.date == r.date,
                    FundTxn.kind == r.kind,
                    FundTxn.units == r.units,
                    FundTxn.amount == r.amount,
                )
            )
        )
        if r.user_set and not (r.action == "switch" and not r.pair_row_id):
            continue
        r.user_set = False
        r.match_transaction_id = None
        if r.existing:
            r.action = "skip"
        elif r.kind in ("dividend_reinvest", "dividend_payout") or (r.kind == "switch_in" and r.pair_row_id):
            r.action = "units"  # a dividend payout is income in your bank statement; units don't change
        elif r.kind == "switch_out" and r.pair_row_id:
            r.action = "switch"
        elif m := _match(db, r, f.account_id, own_ids, claimed):
            r.action, r.match_transaction_id = m
            claimed.add(m[1])
            t = db.get(Transaction, m[1])
            if t is not None:
                bank_votes[t.source_id if r.amount > 0 else t.destination_id] += 1
        else:
            r.action = "before" if start is None or r.date < start else "transfer"

    default_bank = bank_votes.most_common(1)[0][0] if bank_votes else _busiest(db, own_ids)
    for r in cas.rows:
        if not r.user_set and r.action == "transfer":
            if default_bank is None:
                r.action = "before"
            elif r.bank_account_id is None:
                r.bank_account_id = default_bank


def create_draft(db: Session, st: CasStatement, text: str, filename: str, **source) -> CasImport:
    cas = CasImport(
        filename=filename,
        text=text,
        period_from=st.period_from,
        period_to=st.period_to,
        unparsed=st.unparsed[:200],
        **source,
    )
    idx = 0
    for i, f in enumerate(st.funds):
        cf = CasFund(
            idx=i,
            amc=f.amc or None,
            folio=f.folio or None,
            scheme=f.scheme[:255],
            isin=f.isin,
            registrar=f.registrar,
            opening_units=f.opening_units,
            closing_units=f.closing_units,
            nav=f.nav,
            nav_date=f.nav_date,
            cost=f.cost,
            market_value=f.market_value,
        )
        cas.funds.append(cf)
        for t in f.txns:
            cas.rows.append(
                CasRow(
                    idx=idx,
                    fund=cf,
                    date=t.date,
                    description=t.description[:255],
                    kind=t.kind,
                    amount=t.amount,
                    units=t.units,
                    nav=t.nav,
                    balance=t.balance,
                    stamp_duty=t.stamp_duty,
                    action="before",
                )
            )
            idx += 1
    db.add(cas)
    db.flush()
    refresh(db, cas)
    return cas


def revive(db: Session, cas: CasImport) -> bool:
    """An imported CAS whose funds (or their rows) were deleted since: back to a draft, so it
    can be imported again. Funds you left out stay left out."""
    if cas.status != "imported":
        return False
    gone: set[int] = set()
    for f in cas.funds:
        if f.skip:
            continue
        if f.account_id is None or db.get(Account, f.account_id) is None:
            gone.add(f.id)  # its investment was deleted
    for r in cas.rows:
        if r.fund_txn_id and db.get(FundTxn, r.fund_txn_id) is None:
            gone.add(r.fund_id)  # rows deleted from the fund
    if not gone:
        return False
    for f in cas.funds:
        if f.id in gone:
            if f.account_id is not None and db.get(Account, f.account_id) is None:
                f.account_id = None
            f.create_new = False  # suggest again: an existing fund, else a new one
    for r in cas.rows:
        if r.fund_id in gone:
            if r.fund_txn_id and db.get(FundTxn, r.fund_txn_id) is None:
                r.fund_txn_id = None
            if r.transaction_id and db.get(Transaction, r.transaction_id) is None:
                r.transaction_id = None
            r.user_set = False
    cas.status, cas.imported_at = "draft", None
    refresh(db, cas)
    return True


def open_draft(db: Session, candidates: list[tuple[str, str]], filename: str, **source) -> CasImport:
    """The CAS draft for a PDF: the existing one for the same file, else a new one."""
    sha = source.get("file_sha256")
    if sha and (
        existing := db.scalar(select(CasImport).where(CasImport.file_sha256 == sha).order_by(CasImport.id.desc()))
    ):
        revive(db, existing)
        return existing
    reading = best_reading(candidates)
    if reading is None:
        raise bad("This PDF doesn't look like a CAMS / KFintech Consolidated Account Statement (CAS).", "not_cas")
    text, st = reading
    return create_draft(db, st, text, filename, **source)


# ---------------------------------------------------------------- import


def fund_account(db: Session, scheme: str, folio: str | None, amc: str | None) -> Account:
    """A new investment account (kind "mf") for a fund."""
    base = scheme[:110]
    name, n = base, 2
    while db.scalar(
        select(Account.id).where(Account.type == AccountType.investment.value, func.lower(Account.name) == name.lower())
    ):
        name, n = f"{base} ({n})", n + 1
    acct = Account(name=name, type=AccountType.investment.value, account_number=folio, opening_balance=0, active=True)
    db.add(acct)
    db.flush()
    db.add(Investment(account_id=acct.id, kind="mf", institution=amc, number=folio))
    db.flush()
    return acct


def _validate(db: Session, cas: CasImport) -> None:
    for r in cas.rows:
        if r.existing or r.action in ("skip", "units", "before", "switch") or r.fund.skip or r.fund.mode == "fund":
            continue
        if r.action == "transfer" and (r.bank_account_id is None or db.get(Account, r.bank_account_id) is None):
            raise bad(f"Choose the bank account for the {r.date:%d %b %Y} row of {r.fund.scheme}.")
        if r.action in ("link", "convert") and (
            r.match_transaction_id is None or db.get(Transaction, r.match_transaction_id) is None
        ):
            raise bad(
                f"The matched transaction for the {r.date:%d %b %Y} row of {r.fund.scheme} is gone — choose again."
            )


def _transfer(db: Session, on: date, amount: int, desc: str, src: int, dst: int) -> Transaction:
    t = Transaction()
    body = TransactionIn(
        type=TransactionType.transfer, date=on, amount=amount, description=desc[:255],
        source_id=src, destination_id=dst, auto_match_bill=False,
    )  # fmt: skip
    apply_body(db, t, body, is_new=True)
    db.add(t)
    db.flush()
    return t


def do_import(db: Session, cas: CasImport) -> dict:
    if cas.status == "imported":
        raise HTTPException(status.HTTP_409_CONFLICT, "This CAS is already imported.")
    refresh(db, cas)  # rows you didn't change: matched again against what's recorded now
    db.flush()
    _validate(db, cas)
    accounts: dict[int, Account] = {}
    created = 0
    counts_replaced = False
    funds_only = 0
    for f in cas.funds:
        if f.skip:
            continue
        acct = db.get(Account, f.account_id) if f.account_id else None
        if f.mode == "txns" and (acct is None or db.get(Fund, acct.id) is None):
            raise bad(f"“Transactions only” for {f.scheme} needs a fund you already have — pick it under “Goes to”.")
        if acct is None:
            acct = fund_account(db, f.scheme, f.folio, f.amc)
            f.account_id = acct.id
            created += 1
        history = db.scalar(select(FundTxn.id).where(FundTxn.account_id == acct.id).limit(1)) is not None
        if f.mode != "fund":
            mine = [r for r in cas.rows if r.fund_id == f.id and not r.existing and r.action != "skip"]
            has_before = any(r.action == "before" for r in mine)
            from_start = bool(mine) and not f.opening_units  # the CAS shows the fund from its first purchase
            if (has_before or from_start) and already_invested(db, acct.id):
                acct.opening_balance, acct.opening_date = 0, None  # replaced by the CAS's own rows
                counts_replaced = True
        if f.mode == "txns":
            accounts[f.id] = acct  # its rows only: the fund's name, units and price stay as they are
            continue
        if f.mode == "fund":
            funds_only += 1
            if not history and f.cost is not None:  # today's holding: what you paid counts as already invested
                acct.opening_balance = f.cost
                acct.opening_date = cas.period_to or acct.opening_date
        fund = db.get(Fund, acct.id) or Fund(account_id=acct.id, scheme=f.scheme)
        fund.scheme, fund.amc, fund.registrar = f.scheme, f.amc, f.registrar
        fund.isin = f.isin or fund.isin
        fund.folio = f.folio or fund.folio
        if cas.period_to and (fund.units_as_of is None or cas.period_to >= fund.units_as_of):
            last = [r for r in cas.rows if r.fund_id == f.id]
            fund.units = (
                f.closing_units if f.closing_units is not None else (last[-1].balance if last else f.opening_units)
            )
            fund.units_as_of = cas.period_to
            fund.cost = f.cost if f.cost is not None else fund.cost
        if f.nav is not None and (fund.nav_date is None or (f.nav_date and f.nav_date >= fund.nav_date)):
            fund.nav, fund.nav_date, fund.nav_source = f.nav, f.nav_date, "cas"
        db.add(fund)
        if f.mode != "fund":
            accounts[f.id] = acct  # "fund only": its rows aren't imported
    db.flush()

    counts: Counter = Counter()
    rows_by_id = {r.id: r for r in cas.rows}
    for r in cas.rows:
        if r.existing or r.action == "skip" or r.fund_id not in accounts:
            counts["skipped"] += 1
            continue
        acct = accounts[r.fund_id]
        if db.scalar(
            select(FundTxn.id).where(
                FundTxn.account_id == acct.id, FundTxn.date == r.date, FundTxn.kind == r.kind,
                FundTxn.units == r.units, FundTxn.amount == r.amount,
            )
        ):  # fmt: skip
            counts["skipped"] += 1
            continue
        gross = r.amount + r.stamp_duty if r.amount > 0 else r.amount
        ft = FundTxn(
            account_id=acct.id, date=r.date, kind=r.kind, description=r.description, amount=r.amount,
            units=r.units, nav=r.nav, stamp_duty=r.stamp_duty,
        )  # fmt: skip
        label = f"{KIND_LABEL.get(r.kind, r.kind)} · {r.fund.scheme}"
        if r.action == "link":
            ft.transaction_id = r.match_transaction_id
            counts["linked"] += 1
        elif r.action == "convert":
            t = db.get(Transaction, r.match_transaction_id)
            t.type = TransactionType.transfer.value  # type: ignore[union-attr]
            if r.amount > 0:
                t.destination_id = acct.id  # type: ignore[union-attr]
            else:
                t.source_id = acct.id  # type: ignore[union-attr]
            t.category_id = t.budget_id = t.bill_id = None  # type: ignore[union-attr]
            ft.transaction_id = t.id  # type: ignore[union-attr]
            counts["converted"] += 1
        elif r.action == "transfer":
            out = r.amount > 0
            src, dst = (r.bank_account_id, acct.id) if out else (acct.id, r.bank_account_id)
            ft.transaction_id = _transfer(db, r.date, abs(gross), label, src, dst).id  # type: ignore[arg-type]
            counts["created"] += 1
        elif r.action == "switch":
            pair = rows_by_id.get(r.pair_row_id or -1)
            to_acct = accounts.get(pair.fund_id) if pair else None
            if to_acct is None or pair is None:
                raise bad(
                    f"The switch on {r.date:%d %b %Y} goes to a fund you're leaving out or importing as "
                    "“Fund only” — import both funds' transactions, or leave this row out."
                )
            t = _transfer(
                db, r.date, abs(r.amount), f"Switch · {r.fund.scheme} → {pair.fund.scheme}", acct.id, to_acct.id
            )
            ft.transaction_id = r.transaction_id = pair.transaction_id = t.id
            counts["created"] += 1
        elif r.action == "before":
            acct.opening_balance = (acct.opening_balance or 0) + gross
            if acct.opening_date is None or r.date < acct.opening_date:
                acct.opening_date = r.date
            counts["before"] += 1
        else:  # units: no money moves (the switch-in side is recorded on its "out" row)
            counts["units"] += 1
        db.add(ft)
        db.flush()
        r.fund_txn_id = ft.id
        r.transaction_id = r.transaction_id or ft.transaction_id
    for r in cas.rows:  # switch "in" rows point at the transfer made on their "out" row
        if r.kind == "switch_in" and r.pair_row_id and r.fund_txn_id and r.transaction_id:
            ft = db.get(FundTxn, r.fund_txn_id)
            if ft is not None:
                ft.transaction_id = r.transaction_id

    cas.status = "imported"
    cas.imported_at = datetime.now()
    if cas.attachment_id:
        from ..gmail.models import GmailAttachment, GmailMessage

        att = db.get(GmailAttachment, cas.attachment_id)
        msg = db.get(GmailMessage, att.message_id) if att is not None else None
        if msg is not None and msg.status == "new":
            msg.status = "handled"  # the CAS email is dealt with
    db.commit()
    return {
        "funds": len(accounts) + funds_only,
        "funds_only": funds_only,
        "funds_skipped": sum(1 for f in cas.funds if f.skip),
        "accounts_created": created,
        "opening_replaced": int(counts_replaced),
        **counts,
    }

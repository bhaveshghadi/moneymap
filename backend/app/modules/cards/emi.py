"""Card EMIs: a purchase paid back in monthly instalments.

Spending is counted ONCE, in full, when you buy (the purchase expense). After that:
- "converted to EMI" credit on the card   -> transfer plan -> card (the debt moves to the plan)
- each month's principal on the statement -> transfer card -> plan (it lands on the card bill)
- interest, GST on interest, processing fee -> expenses from the card (Card Fees & Interest),
  linked to the plan by transaction.emi_id
The plan's own account (type emi_plan) holds the principal still to pay.
"""

import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...core.dates import add_months
from ...db import get_db
from ..accounts.models import Account, AccountType
from ..accounts.service import find_or_create_counterparty
from ..auth.security import current_user
from ..categories.models import Category
from ..transactions.models import Transaction, TransactionType
from ..transactions.schemas import TransactionIn
from ..transactions.service import apply_body
from .models import CardEmi, CreditCard

router = APIRouter(prefix="/cards", tags=["card emis"], dependencies=[Depends(current_user)])

# "Principal Amount Amortization - <3/6>Flipkart Internet PVT LT"
PRINCIPAL_RE = re.compile(r"principal[^<]{0,40}<\s*(\d{1,2})\s*/\s*(\d{1,2})\s*>\s*([A-Za-z][^\d]{0,40})?", re.I)
# "Interest Amount Amortization - <3/6>Flipkart ..."
INTEREST_RE = re.compile(r"interest[^<]{0,40}<\s*(\d{1,2})\s*/\s*(\d{1,2})\s*>\s*([A-Za-z][^\d]{0,40})?", re.I)
# the credit that moves a purchase off the bill into an EMI
CONVERSION_RE = re.compile(r"conver(t|ted|sion)\b.{0,30}\bemi\b|\bemi\b.{0,30}conver(t|ted|sion)|emi booking", re.I)
GST_RE = re.compile(r"\b(i|c|s)?gst\b", re.I)
STOP_WORDS = {"the", "pvt", "ltd", "lt", "india", "internet", "private", "limited", "in", "co", "and"}


# ---------------------------------------------------------------- schemas


class EmiIn(BaseModel):
    kind: str = Field(pattern="^(converted|checkout|existing)$")
    name: str = Field(min_length=1, max_length=120)
    principal: int = Field(gt=0, le=10**13)  # paise: the purchase amount
    tenure: int = Field(ge=1, le=120)
    start_date: date  # first instalment
    instalment: int | None = Field(default=None, gt=0, le=10**13)
    interest_rate: float | None = Field(default=None, ge=0, le=60)  # yearly %
    processing_fee: int | None = Field(default=None, ge=0, le=10**12)
    no_cost: bool = False
    # converted: the card purchase that was converted, and when
    purchase_txn_id: int | None = None
    converted_on: date | None = None
    # checkout: the purchase is recorded with the plan
    purchase_date: date | None = None
    category_id: int | None = None
    # existing (running before you started tracking): what's left now
    outstanding: int | None = Field(default=None, ge=0, le=10**13)
    paid_before: int | None = Field(default=None, ge=0, le=120)
    link_past: bool = True  # move matching instalment / interest rows from imported statements onto the plan
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class EmiOut(BaseModel):
    id: int
    card_id: int  # the card's account id
    account_id: int  # the plan's own account
    name: str
    kind: str
    principal: int
    tenure: int
    instalment: int | None
    interest_rate: float | None
    processing_fee: int | None
    no_cost: bool
    start_date: date
    finish_date: date
    paid_count: int
    outstanding: int
    principal_paid: int
    interest_paid: int  # interest + GST + fees linked to the plan
    next_date: date | None
    status: str  # active | closed
    closed_on: date | None
    purchase_txn_id: int | None
    notes: str | None


class EmiCreated(BaseModel):
    emi: EmiOut
    linked_instalments: int
    linked_charges: int


class EmiCloseIn(BaseModel):
    date: date


# ---------------------------------------------------------------- helpers


def _bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def merchant_words(text: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in STOP_WORDS}


def match_plan(plans: list[CardEmi], tenure: int, merchant: str | None, strict: bool = False) -> CardEmi | None:
    """The plan with this many instalments whose name shares a word with the merchant
    text — or, unless `strict`, the only plan with that tenure (statement rows you review)."""
    same = [p for p in plans if p.tenure == tenure and p.closed_on is None]
    words = merchant_words(merchant)
    named = [p for p in same if words & merchant_words(p.name)]
    if len(named) == 1:
        return named[0]
    if strict:
        return None
    return same[0] if len(same) == 1 else None


def plans_of(db: Session, card_account_id: int) -> list[CardEmi]:
    return list(
        db.scalars(
            select(CardEmi)
            .join(CreditCard, CardEmi.card_id == CreditCard.id)
            .where(CreditCard.account_id == card_account_id)
            .order_by(CardEmi.id)
        )
    )


def _balance(db: Session, a: Account) -> int:
    inc = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.destination_id == a.id))
    out = db.scalar(select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.source_id == a.id))
    return a.opening_balance + int(inc) - int(out)


def emi_out(db: Session, e: CardEmi, card_account_id: int, today: date | None = None) -> EmiOut:
    today = today or date.today()
    outstanding = max(0, -_balance(db, e.account))
    principal_rows = list(
        db.scalars(
            select(Transaction).where(
                Transaction.destination_id == e.account_id, Transaction.source_id == card_account_id
            )
        ).unique()
    )
    seen_k = [int(m.group(1)) for t in principal_rows if (m := PRINCIPAL_RE.search(t.description))]
    paid = min(e.tenure, max([e.paid_before + len(principal_rows), *seen_k]))
    charges = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.emi_id == e.id, Transaction.type == TransactionType.withdrawal.value
        )
    )
    closed = e.closed_on is not None or (outstanding == 0 and paid >= e.tenure)
    return EmiOut(
        id=e.id,
        card_id=card_account_id,
        account_id=e.account_id,
        name=e.name,
        kind=e.kind,
        principal=e.principal,
        tenure=e.tenure,
        instalment=e.instalment,
        interest_rate=e.interest_rate_bp / 100 if e.interest_rate_bp is not None else None,
        processing_fee=e.processing_fee,
        no_cost=e.no_cost,
        start_date=e.start_date,
        finish_date=add_months(e.start_date, e.tenure - 1),
        paid_count=paid,
        outstanding=outstanding,
        principal_paid=max(0, e.principal - outstanding),
        interest_paid=int(charges),
        next_date=None if closed else add_months(e.start_date, paid),
        status="closed" if closed else "active",
        closed_on=e.closed_on,
        purchase_txn_id=e.purchase_txn_id,
        notes=e.notes,
    )


def emi_outstanding(db: Session, card_account_id: int) -> int:
    return sum(max(0, -_balance(db, e.account)) for e in plans_of(db, card_account_id))


def _unique_name(db: Session, base: str) -> str:
    name, n = base[:110], 2
    while db.scalar(
        select(Account.id).where(Account.type == AccountType.emi_plan.value, func.lower(Account.name) == name.lower())
    ):
        name = f"{base[:105]} ({n})"
        n += 1
    return name


def link_past_rows(db: Session, e: CardEmi, card_account_id: int) -> tuple[int, int]:
    """Instalment rows already imported as card expenses ("Principal ... <k/n> Merchant",
    the merchant sharing a word with the plan's name) become transfers card -> plan;
    interest and GST rows of the same instalments are linked to the plan.
    Returns (instalments, charges)."""
    plans = plans_of(db, card_account_id)
    rows = list(
        db.scalars(
            select(Transaction)
            .where(
                Transaction.source_id == card_account_id,
                Transaction.type == TransactionType.withdrawal.value,
                or_(Transaction.emi_id.is_(None), Transaction.emi_id == e.id),
            )
            .order_by(Transaction.date, Transaction.id)
        ).unique()
    )
    instalments = charges = 0
    interest_dates: set[date] = set()
    for t in rows:
        if (m := PRINCIPAL_RE.search(t.description)) and match_plan(plans, int(m.group(2)), m.group(3), True) is e:
            t.type = TransactionType.transfer.value
            t.destination_id = e.account_id
            t.category_id = t.budget_id = t.bill_id = None
            t.emi_id = e.id
            instalments += 1
        elif (m := INTEREST_RE.search(t.description)) and match_plan(plans, int(m.group(2)), m.group(3), True) is e:
            if t.emi_id != e.id:
                t.emi_id = e.id
                charges += 1
            interest_dates.add(t.date)
    for t in rows:  # GST on that interest: same day, no merchant of its own
        gst = t.type == TransactionType.withdrawal.value and t.emi_id is None and t.date in interest_dates
        if gst and GST_RE.search(t.description):
            t.emi_id = e.id
            charges += 1
    db.flush()
    return instalments, charges


def _card(db: Session, card_account_id: int) -> CreditCard:
    card = db.scalar(select(CreditCard).where(CreditCard.account_id == card_account_id))
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    return card


def _emi(db: Session, card: CreditCard, emi_id: int) -> CardEmi:
    e = db.get(CardEmi, emi_id)
    if e is None or e.card_id != card.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "EMI not found")
    return e


def _new_txn(db: Session, body: dict) -> Transaction:
    t = Transaction()
    apply_body(db, t, TransactionIn(**body), is_new=True)
    db.add(t)
    db.flush()
    return t


# ---------------------------------------------------------------- API


@router.get("/{card_account_id}/emis", response_model=list[EmiOut])
def list_emis(card_account_id: int, db: Session = Depends(get_db)) -> list[EmiOut]:
    _card(db, card_account_id)
    return [emi_out(db, e, card_account_id) for e in plans_of(db, card_account_id)]


@router.post("/{card_account_id}/emis", response_model=EmiCreated, status_code=201)
def create_emi(card_account_id: int, body: EmiIn, db: Session = Depends(get_db)) -> EmiCreated:
    card = _card(db, card_account_id)
    if body.kind == "converted":
        p = db.get(Transaction, body.purchase_txn_id) if body.purchase_txn_id else None
        if p is None or p.type != TransactionType.withdrawal.value or p.source_id != card_account_id:
            raise _bad("Choose the card purchase that was converted to EMI.")
    if body.kind == "existing" and body.outstanding is None:
        raise _bad("Enter how much principal is still left to pay.")
    if body.kind == "checkout" and body.category_id is not None:
        c = db.get(Category, body.category_id)
        if c is None or c.kind != "expense":
            raise _bad("Choose an expense category.")

    plan_account = Account(
        name=_unique_name(db, f"EMI · {body.name}"),
        type=AccountType.emi_plan.value,
        opening_balance=0,
        opening_date=None,
        active=True,
    )
    db.add(plan_account)
    db.flush()
    e = CardEmi(
        card_id=card.id,
        account_id=plan_account.id,
        name=body.name,
        kind=body.kind,
        principal=body.principal,
        tenure=body.tenure,
        instalment=body.instalment,
        interest_rate_bp=round(body.interest_rate * 100) if body.interest_rate is not None else None,
        processing_fee=body.processing_fee,
        no_cost=body.no_cost,
        start_date=body.start_date,
        paid_before=0,
        purchase_txn_id=body.purchase_txn_id if body.kind == "converted" else None,
        notes=(body.notes or "").strip() or None,
    )
    db.add(e)
    db.flush()
    e.account = plan_account

    if body.kind == "converted":
        t = _new_txn(
            db,
            {
                "type": "transfer",
                "date": body.converted_on or date.today(),
                "amount": body.principal,
                "description": f"Converted to EMI: {body.name}",
                "source_id": plan_account.id,
                "destination_id": card_account_id,
            },
        )
        t.emi_id = e.id
        e.created_txn_id = t.id
    elif body.kind == "checkout":
        t = _new_txn(
            db,
            {
                "type": "withdrawal",
                "date": body.purchase_date or body.start_date,
                "amount": body.principal,
                "description": f"{body.name} (EMI)",
                "source_id": plan_account.id,
                "destination_name": body.name,
                "category_id": body.category_id,
                "auto_match_bill": False,
            },
        )
        t.emi_id = e.id
        e.created_txn_id = t.id

    linked = (0, 0)
    if body.link_past:
        linked = link_past_rows(db, e, card_account_id)

    if body.kind == "existing":
        # the plan owes what's left now, after any instalments linked above
        linked_principal = db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.destination_id == plan_account.id, Transaction.source_id == card_account_id
            )
        )
        plan_account.opening_balance = -(body.outstanding + int(linked_principal))
        plan_account.opening_date = body.start_date
        per = body.principal / body.tenure
        e.paid_before = (
            body.paid_before
            if body.paid_before is not None
            else max(0, min(body.tenure, round((body.principal - body.outstanding) / per)) - linked[0])
        )
    db.commit()
    db.refresh(e)
    return EmiCreated(emi=emi_out(db, e, card_account_id), linked_instalments=linked[0], linked_charges=linked[1])


@router.post("/{card_account_id}/emis/{emi_id}/close", response_model=EmiOut)
def close_early(card_account_id: int, emi_id: int, body: EmiCloseIn, db: Session = Depends(get_db)) -> EmiOut:
    """Paid off early (foreclosure): what's left moves onto the card bill."""
    card = _card(db, card_account_id)
    e = _emi(db, card, emi_id)
    left = max(0, -_balance(db, e.account))
    if left:
        t = _new_txn(
            db,
            {
                "type": "transfer",
                "date": body.date,
                "amount": left,
                "description": f"EMI closed early: {e.name}",
                "source_id": card_account_id,
                "destination_id": e.account_id,
            },
        )
        t.emi_id = e.id
    e.closed_on = body.date
    db.commit()
    return emi_out(db, e, card_account_id)


@router.delete("/{card_account_id}/emis/{emi_id}", status_code=204)
def delete_emi(card_account_id: int, emi_id: int, db: Session = Depends(get_db)) -> None:
    """Remove a plan. The conversion / purchase it made is deleted; instalments it
    linked go back to being card expenses (payee "EMI instalment")."""
    card = _card(db, card_account_id)
    e = _emi(db, card, emi_id)
    made = db.get(Transaction, e.created_txn_id) if e.created_txn_id else None
    if made is not None:
        db.delete(made)
    db.flush()
    payee = find_or_create_counterparty(db, "EMI instalment", AccountType.expense)
    for t in db.scalars(
        select(Transaction).where(
            or_(Transaction.source_id == e.account_id, Transaction.destination_id == e.account_id)
        )
    ).unique():
        if t.source_id == card_account_id and t.destination_id == e.account_id:
            t.type = TransactionType.withdrawal.value
            t.destination_id = payee.id
            t.emi_id = None
        else:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"“{t.description}” on {t.date:%d %b %Y} uses this EMI — change or delete it first.",
            )
    for t in db.scalars(select(Transaction).where(Transaction.emi_id == e.id)).unique():
        t.emi_id = None
    db.flush()
    a = e.account
    db.delete(e)
    db.flush()
    db.delete(a)
    db.commit()

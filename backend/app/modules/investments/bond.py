"""Bonds: the expected payout schedule next to what was received, and recording a payout.

A payout is split the way it really is: the interest part is income (category Interest, net of
TDS) and the principal part is money coming back from the bond (a transfer bond -> bank), so the
bond's outstanding value falls only by the principal."""

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..accounts.models import Account, AccountType
from ..categories.models import Category
from ..transactions.models import Transaction, TransactionType
from ..transactions.schemas import TransactionIn
from ..transactions.service import apply_body, txn_out
from .models import BondPayout, Investment
from .schemas import BondOut, BondPayoutOut, BondRowOut, PayoutIn
from .values import Valued, bond_face, bond_schedule

MATCH_DAYS = 20  # a payout recorded without its row belongs to the nearest scheduled date within this


def _bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def _payouts(db: Session, inv: Investment) -> list[BondPayout]:
    return list(
        db.scalars(
            select(BondPayout).where(BondPayout.account_id == inv.account_id).order_by(BondPayout.date, BondPayout.id)
        )
    )


def bond_out(db: Session, inv: Investment, v: Valued, today: date) -> BondOut:
    payouts = _payouts(db, inv)
    by_n = {p.n: p for p in payouts if p.n is not None}
    rows = [
        BondRowOut(
            n=r.n,
            date=r.date,
            interest=r.interest,
            principal=r.principal,
            outstanding=r.outstanding,
            payout_id=by_n[r.n].id if r.n in by_n else None,
            status="received" if r.n in by_n else "missed" if r.date < today else "due",
        )
        for r in bond_schedule(inv)
    ]
    split = {p.principal_txn_id for p in payouts if p.principal_txn_id}
    unsplit = db.scalars(
        select(Transaction)
        .where(Transaction.source_id == inv.account_id, Transaction.type == TransactionType.transfer.value)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
    ).unique()
    return BondOut(
        face=bond_face(inv),
        outstanding=v.value,
        principal_back=v.money_out,
        interest_received=sum(p.interest for p in payouts),
        tds=sum(p.tds for p in payouts),
        schedule=rows,
        payouts=[
            BondPayoutOut(
                id=p.id,
                date=p.date,
                n=p.n,
                interest=p.interest,
                principal=p.principal,
                tds=p.tds,
                received=p.interest - p.tds + p.principal,
                interest_txn_id=p.interest_txn_id,
                principal_txn_id=p.principal_txn_id,
            )
            for p in reversed(payouts)
        ],
        unsplit=[txn_out(t) for t in unsplit if t.id not in split],
    )


def _interest_category(db: Session) -> int | None:
    return db.scalar(select(Category.id).where(func.lower(Category.name) == "interest", Category.kind == "income"))


def _row_for(db: Session, inv: Investment, on: date) -> int | None:
    """The scheduled row nearest `on` that has no payout yet."""
    taken = {p.n for p in _payouts(db, inv) if p.n is not None}
    free = [r for r in bond_schedule(inv) if r.n not in taken and abs((r.date - on).days) <= MATCH_DAYS]
    return min(free, key=lambda r: abs((r.date - on).days)).n if free else None


def record_payout(db: Session, inv: Investment, body: PayoutIn, bank: Account) -> BondPayout:
    if body.tds > body.interest:
        raise _bad("TDS can't be more than the interest.")
    net = body.interest - body.tds
    received = net + body.principal
    if received <= 0:
        raise _bad("Enter the interest or the principal received.")
    n = body.n if body.n is not None else _row_for(db, inv, body.date)
    if n is not None and db.scalar(
        select(BondPayout.id).where(BondPayout.account_id == inv.account_id, BondPayout.n == n)
    ):
        raise _bad(f"Payout {n} is already recorded.")
    issuer = (inv.institution or inv.account.name).strip()
    what = f"payout {n}" if n is not None else "payout"
    int_desc = f"Interest · {inv.account.name} · {what}" + (f" (TDS ₹{body.tds / 100:,.2f})" if body.tds else "")
    cat = _interest_category(db)

    principal_t: Transaction | None = None
    interest_t: Transaction | None = None
    if body.transaction_id is not None:
        t = db.get(Transaction, body.transaction_id)
        if t is None:
            raise _bad("That payment no longer exists.")
        if t.destination_id != bank.id:
            raise _bad("That payment didn't go into the bank account chosen.")
        if t.source_id != inv.account_id and t.type != TransactionType.deposit.value:
            raise _bad("Only money received (income, or money back from this bond) can be split.")
        if t.amount != received:
            raise _bad(
                f"That payment is ₹{t.amount / 100:,.2f}; interest − TDS + principal must add up to it "
                f"(now ₹{received / 100:,.2f})."
            )
        if body.principal > 0:
            t.type = TransactionType.transfer.value
            t.source_id = inv.account_id
            t.amount = body.principal
            t.category_id = t.budget_id = t.bill_id = None
            t.description = f"Principal back · {inv.account.name} · {what}"
            principal_t = t
        else:
            revenue = _revenue(db, issuer)
            t.type = TransactionType.deposit.value
            t.source_id = revenue.id
            t.amount = net
            t.category_id = cat
            t.budget_id = t.bill_id = None
            t.description = int_desc
            interest_t = t
    elif body.principal > 0:
        principal_t = _new(
            db,
            TransactionIn(
                type="transfer",  # type: ignore[arg-type]
                date=body.date,
                amount=body.principal,
                description=f"Principal back · {inv.account.name} · {what}",
                source_id=inv.account_id,
                destination_id=bank.id,
                auto_match_bill=False,
            ),
        )
    if interest_t is None and net > 0:
        interest_t = _new(
            db,
            TransactionIn(
                type="deposit",  # type: ignore[arg-type]
                date=principal_t.date if principal_t else body.date,
                amount=net,
                description=int_desc,
                source_id=_revenue(db, issuer).id,
                destination_id=bank.id,
                category_id=cat,
                auto_match_bill=False,
            ),
        )
    p = BondPayout(
        account_id=inv.account_id,
        date=body.date,
        n=n,
        interest=body.interest,
        principal=body.principal,
        tds=body.tds,
        interest_txn_id=interest_t.id if interest_t else None,
        principal_txn_id=principal_t.id if principal_t else None,
    )
    db.add(p)
    db.flush()
    return p


def _revenue(db: Session, issuer: str) -> Account:
    from ..accounts.service import find_or_create_counterparty

    return find_or_create_counterparty(db, issuer[:120], AccountType.revenue)


def _new(db: Session, body: TransactionIn) -> Transaction:
    t = Transaction()
    apply_body(db, t, body, is_new=True)
    db.add(t)
    db.flush()
    return t


def _from_outside(db: Session, t: Transaction) -> bool:
    """Came from a bank statement or an Inbox email: undoing must not lose it."""
    from ..transactions.service import statements_of

    return bool(t.gmail_message_id) or bool(statements_of(db, [t.id]))


def delete_payout(db: Session, inv: Investment, payout_id: int) -> None:
    """Undo a payout. Entries it added are deleted; a payment that came from a statement or an
    email goes back to one "money back from the bond" entry for the whole amount, to split again."""
    p = db.get(BondPayout, payout_id)
    if p is None or p.account_id != inv.account_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payout not found")
    txns = [t for tid in (p.principal_txn_id, p.interest_txn_id) if tid and (t := db.get(Transaction, tid))]
    keep = next((t for t in txns if _from_outside(db, t)), None)
    if keep is not None:
        keep.type = TransactionType.transfer.value
        keep.source_id = inv.account_id
        keep.amount = p.interest - p.tds + p.principal
        keep.category_id = keep.budget_id = keep.bill_id = None
        keep.description = f"From investment: {inv.account.name}"
    for t in txns:
        if t is not keep:
            db.delete(t)
    db.delete(p)
    db.flush()

"""Bills: payments linked to them, status, upcoming list and matching new expenses."""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..transactions.models import Transaction
from .models import Bill
from .schedule import bill_state, monthly_cost
from .schemas import BillDue, BillOut

UPCOMING_ORDER = {"overdue": 0, "due_soon": 1, "upcoming": 2}


def payments(db: Session, bill_ids: list[int] | None = None) -> dict[int, list[tuple[date, int]]]:
    """bill id -> [(date, amount)] of linked expenses, oldest first."""
    q = select(Transaction.bill_id, Transaction.date, Transaction.amount).where(Transaction.bill_id.is_not(None))
    if bill_ids is not None:
        q = q.where(Transaction.bill_id.in_(bill_ids))
    out: dict[int, list[tuple[date, int]]] = defaultdict(list)
    for bid, d, amt in db.execute(q.order_by(Transaction.date, Transaction.id)):
        out[bid].append((d, amt))
    return out


def bill_out(b: Bill, paid: list[tuple[date, int]]) -> BillOut:
    st = bill_state(b, [d for d, _ in paid])
    out = BillOut.model_validate(b)
    out.next_due = st.next_due
    out.status = st.status
    if paid:
        out.last_paid_date, out.last_paid_amount = paid[-1]
    out.monthly_cost = monthly_cost(b)
    out.transaction_count = len(paid)
    return out


def all_bills(db: Session) -> list[BillOut]:
    bills = list(db.scalars(select(Bill).order_by(Bill.active.desc(), func.lower(Bill.name))))
    pays = payments(db, [b.id for b in bills])
    return [bill_out(b, pays.get(b.id, [])) for b in bills]


def upcoming(db: Session, days: int = 30) -> list[BillDue]:
    """Overdue bills and those due in the next `days` days, most urgent first."""
    horizon = date.today() + timedelta(days=days)
    out = [
        BillDue(
            bill_id=b.id,
            name=b.name,
            due=b.next_due,
            status=b.status,
            expected=(b.amount_min + b.amount_max) // 2,
        )
        for b in all_bills(db)
        if b.status in UPCOMING_ORDER and b.next_due and b.next_due <= horizon
    ]
    return sorted(out, key=lambda x: (UPCOMING_ORDER[x.status], x.due))


def match_bill(db: Session, description: str, payee: str, amount: int) -> Bill | None:
    """First active bill with a match word in the description or payee whose
    amount range contains `amount` (the bill's name is used when it has no words)."""
    hay = f"{description} {payee}".lower()
    for bill in db.scalars(select(Bill).where(Bill.active.is_(True)).order_by(Bill.id)):
        words = [w.strip().lower() for w in (bill.match or bill.name).split(",") if w.strip()]
        if bill.amount_min <= amount <= bill.amount_max and any(w in hay for w in words):
            return bill
    return None

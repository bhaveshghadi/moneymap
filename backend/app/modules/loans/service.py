"""Loan state from its terms, its changes (part-payments, rate changes) and the payments
linked to it (transaction.loan_id).

Which EMIs are paid: the first `paid_before` (paid before tracking started) plus every
EMI number (`loan_n`) a linked EMI / principal payment is recorded against. What's
left = the amount borrowed minus the principal of the paid EMIs and the part-payments.
"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..categories.models import Category
from ..transactions.models import Transaction
from .maths import Event, Row, build, build_events, first_emi_interest, implied_rate_bp, schedule_for
from .models import Loan, LoanEvent
from .schemas import EventOut, LoanDetail, LoanDue, LoanOut, NextEmi, RowOut

PAID_PARTS = ("emi", "principal")
EMI_CATEGORY = "Loan / EMI"
INTEREST_CATEGORY = "Loan Interest"
FEE_CATEGORY = "Bank Charges & Fees"


def supports_changes(loan: Loan) -> bool:
    """Part-payments and rate changes need a reducing-balance schedule (an amount and a rate)."""
    return loan.method == "reducing" or (loan.method == "emi_only" and bool(loan.principal))


def base_rate(loan: Loan) -> int:
    if loan.method == "emi_only" and loan.principal:
        return implied_rate_bp(loan.principal, loan.emi, loan.tenure)
    return loan.rate_bp or 0


def first_interest(loan: Loan) -> int | None:
    """EMI 1's interest when the lender counts the days from the loan being paid out (else None)."""
    if loan.method != "reducing":
        return None
    return first_emi_interest(
        loan.principal, loan.rate_bp, loan.first_emi_date, loan.disbursed_date, loan.first_interest
    )


def first_interest_days(loan: Loan) -> int | None:
    if first_interest(loan) is None:
        return None
    return (loan.first_emi_date - loan.disbursed_date).days  # type: ignore[operator]


def last_emi_check(loan: Loan, rows: list[Row]) -> tuple[bool, str | None]:
    """Is the last EMI far (> 2%) from the EMI on a reducing-balance loan without changes? That
    usually means the lender counts the first EMI's interest by days. Returns (off, the
    first-interest mode that makes the last EMI fit, if the taken-on date is known)."""
    if loan.method != "reducing" or loan.events or not rows or len(rows) != loan.tenure or not loan.emi:
        return False, None
    limit = loan.emi * 2 // 100

    def miss(rs: list[Row]) -> int:
        return abs(rs[-1].emi - loan.emi) if len(rs) == loan.tenure else loan.emi

    if miss(rows) <= limit:
        return False, None
    best, best_miss = None, limit + 1
    for mode in ("days360", "days365", "month"):
        if mode == loan.first_interest:
            continue
        bpi = first_emi_interest(loan.principal, loan.rate_bp, loan.first_emi_date, loan.disbursed_date, mode)
        if mode != "month" and bpi is None:
            continue
        try:
            m = miss(
                build(
                    loan.principal or 0,
                    loan.rate_bp or 0,
                    loan.emi,
                    loan.tenure,
                    loan.first_emi_date,
                    first_interest=bpi,
                )
            )
        except ValueError:
            continue
        if m < best_miss:
            best, best_miss = mode, m
    return True, best


def to_events(evs: list[LoanEvent]) -> list[Event]:
    return [Event(e.date, e.kind, e.mode, e.amount or 0, e.rate_bp or 0) for e in evs]


def schedule_with(loan: Loan, events: list[Event]) -> tuple[list[Row], list]:
    if supports_changes(loan) and events:
        return build_events(
            loan.principal or 0,
            base_rate(loan),
            loan.emi,
            loan.tenure,
            loan.first_emi_date,
            events,
            first_interest=first_interest(loan),
        )
    rows = schedule_for(
        loan.method, loan.principal, loan.rate_bp, loan.emi, loan.tenure, loan.first_emi_date, first_interest(loan)
    )
    return rows, []


def schedule(loan: Loan) -> list[Row]:
    return schedule_with(loan, to_events(loan.events))[0]


def paid_numbers(db: Session, loan: Loan) -> set[int]:
    linked = set(
        db.scalars(
            select(Transaction.loan_n).where(
                Transaction.loan_id == loan.id, Transaction.loan_part.in_(PAID_PARTS), Transaction.loan_n.is_not(None)
            )
        )
    )
    return set(range(1, loan.paid_before + 1)) | linked


def category_id(db: Session, name: str) -> int | None:
    return db.scalar(select(Category.id).where(func.lower(Category.name) == name.lower()))


def prepaid(loan: Loan) -> int:
    return sum(e.amount or 0 for e in loan.events if e.kind == "prepay")


def loan_out(db: Session, loan: Loan, today: date | None = None, detail: bool = False) -> LoanOut:
    today = today or date.today()
    rows, applied = schedule_with(loan, to_events(loan.events))
    paid = {n for n in paid_numbers(db, loan) if n <= len(rows)}
    borrowed = loan.principal if loan.principal else sum(r.principal for r in rows)
    outstanding = max(0, borrowed - sum(r.principal for r in rows if r.n in paid) - prepaid(loan))
    closed = loan.closed_on is not None or (bool(rows) and len(paid) >= len(rows)) or outstanding == 0
    nxt = next((r for r in rows if r.n not in paid), None) if not closed else None
    if loan.count_mode == "interest_only":
        actual = db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.loan_id == loan.id, Transaction.loan_part == "interest"
            )
        )
        interest_paid = int(actual) + sum(r.interest for r in rows if r.n <= loan.paid_before)
    else:
        interest_paid = sum(r.interest for r in rows if r.n in paid)
    last_off, suggestion = last_emi_check(loan, rows)
    rate_worked_out = loan.method == "emi_only" and bool(loan.principal)
    rate_bp = base_rate(loan) if (rate_worked_out or loan.rate_bp is not None) else None
    rate_changes = [e for e in loan.events if e.kind == "rate" and e.date <= today]
    current_rate = rate_changes[-1].rate_bp if rate_changes else rate_bp
    current_emi = nxt.emi if nxt else (applied[-1][2] if applied and applied[-1][2] else loan.emi)
    by_date = {(ev.date, ev.kind, ev.amount, ev.rate_bp): (n, emi) for ev, n, emi in applied}
    events = []
    for e in loan.events:
        n, emi_after = by_date.get((e.date, e.kind, e.amount or 0, e.rate_bp or 0), (None, None))
        events.append(
            EventOut(
                id=e.id,
                kind=e.kind,
                date=e.date,
                mode=e.mode,
                amount=e.amount,
                rate=e.rate_bp / 100 if e.rate_bp is not None else None,
                before_n=n,
                emi_after=emi_after,
                txn_id=e.txn_id,
            )
        )
    data = dict(
        id=loan.account_id,
        loan_id=loan.id,
        name=loan.account.name,
        lender=loan.lender,
        kind=loan.kind,
        loan_number=loan.loan_number,
        method=loan.method,
        count_mode=loan.count_mode,
        principal=loan.principal,
        rate=rate_bp / 100 if rate_bp is not None else None,
        current_rate=current_rate / 100 if current_rate is not None else None,
        rate_worked_out=rate_worked_out,
        tenure=loan.tenure,
        emi=loan.emi,
        current_emi=current_emi,
        first_emi_date=loan.first_emi_date,
        disbursed_date=loan.disbursed_date,
        first_interest=loan.first_interest,
        first_interest_days=first_interest_days(loan),
        last_emi_off=last_off,
        first_interest_suggestion=suggestion,
        end_date=rows[-1].date if rows else loan.first_emi_date,
        pay_from_id=loan.pay_from_id,
        pay_from_name=loan.pay_from.name if loan.pay_from else None,
        paid_before=loan.paid_before,
        paid_count=len(paid),
        outstanding=0 if closed and loan.closed_on is None else outstanding,
        prepaid=prepaid(loan),
        total_interest=sum(r.interest for r in rows),
        total_payable=sum(r.emi for r in rows) + prepaid(loan),
        interest_paid=interest_paid,
        next=NextEmi(
            **{k: getattr(nxt, k) for k in ("n", "date", "emi", "principal", "interest")}, overdue=nxt.date < today
        )
        if nxt
        else None,
        status="closed" if closed else "active",
        closed_on=loan.closed_on,
        notes=loan.notes,
        supports_changes=supports_changes(loan),
        events=events,
    )
    if detail:
        return LoanDetail(**data, schedule=[RowOut(**r.__dict__, paid=r.n in paid) for r in rows])
    return LoanOut(**data)


def all_loans(db: Session, active_only: bool = False) -> list[LoanOut]:
    out = [loan_out(db, ln) for ln in db.scalars(select(Loan).order_by(Loan.id)).unique()]
    return [x for x in out if x.status == "active"] if active_only else out


def loan_dues(db: Session, days: int = 30) -> list[LoanDue]:
    horizon = date.today() + timedelta(days=days)
    out = [
        LoanDue(
            loan_id=x.id,
            name=x.name,
            date=x.next.date,
            amount=x.next.emi,
            n=x.next.n,
            tenure=x.tenure,
            overdue=x.next.overdue,
        )
        for x in all_loans(db, active_only=True)
        if x.next and x.next.date <= horizon
    ]
    return sorted(out, key=lambda d: (not d.overdue, d.date))


def monthly_emis(db: Session) -> int:
    """The EMIs of active loans: an essential monthly cost for the emergency fund."""
    return sum(x.current_emi for x in all_loans(db, active_only=True))


def remaining(rows: list[Row], after: date) -> dict:
    """EMIs dated after `after`: count, interest, last date, first EMI amount."""
    left = [r for r in rows if r.date > after]
    return {
        "emi": left[0].emi if left else 0,
        "months": len(left),
        "interest": sum(r.interest for r in left),
        "end_date": left[-1].date if left else None,
    }

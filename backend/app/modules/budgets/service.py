"""Monthly budget amounts (manual / fixed / rollover) and spending against them."""

from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.dates import add_months, month_bounds
from ..transactions.models import Transaction, TransactionType
from .models import Budget, BudgetLimit, BudgetMode
from .schemas import BudgetMonth, BudgetOut

ROLLOVER_MAX_MONTHS = 240  # how far back a rollover chain is followed


def parse_month(month: str | None) -> tuple[date, str]:
    """'YYYY-MM' (default: this month) -> (first day, label); 422 when malformed."""
    try:
        start, _, label = month_bounds(month)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "month must look like YYYY-MM") from None
    return start, label


def spent_in(db: Session, budget_id: int, m: date) -> int:
    """Expenses in this budget during the month starting at `m`."""
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.budget_id == budget_id,
                Transaction.type == TransactionType.withdrawal.value,
                Transaction.date >= m,
                Transaction.date < add_months(m, 1, 1),
            )
        )
        or 0
    )


def limit_for(db: Session, budget: Budget, m: date, _depth: int = 0) -> BudgetLimit | None:
    """The amount for month `m`, filling in fixed / rollover months when first asked for.

    Filled-in months run from the month the budget was created up to the current
    month; future months stay empty until set by hand. Rollover carries last
    month's leftover (or overspend) and never goes below zero.
    """
    lim = db.scalar(select(BudgetLimit).where(BudgetLimit.budget_id == budget.id, BudgetLimit.month == m))
    if lim is not None or budget.mode == BudgetMode.manual or not budget.active:
        return lim
    this_month = date.today().replace(day=1)
    created = budget.created_at.date().replace(day=1) if budget.created_at else this_month
    if m < created or m > this_month:
        return None
    amount = budget.amount
    if budget.mode == BudgetMode.rollover and m > created and _depth < ROLLOVER_MAX_MONTHS:
        prev_m = add_months(m, -1, 1)
        prev = limit_for(db, budget, prev_m, _depth + 1)
        if prev is not None:
            amount = max(0, amount + prev.amount - spent_in(db, budget.id, prev_m))
    lim = BudgetLimit(budget_id=budget.id, month=m, amount=amount, auto_generated=True)
    db.add(lim)
    db.flush()
    return lim


def reset_auto_limits(db: Session, budget: Budget) -> None:
    """After the mode or amount changes, drop filled-in amounts from this month on so
    they are worked out again. Amounts set by hand and past months stay."""
    for lim in db.scalars(
        select(BudgetLimit).where(
            BudgetLimit.budget_id == budget.id,
            BudgetLimit.auto_generated.is_(True),
            BudgetLimit.month >= date.today().replace(day=1),
        )
    ):
        db.delete(lim)
    db.flush()


def budget_out(db: Session, b: Budget, m: date, label: str) -> BudgetOut:
    lim = limit_for(db, b, m)
    spent = spent_in(db, b.id, m)
    out = BudgetOut.model_validate(b)
    out.month = label
    out.limit = lim.amount if lim else None
    out.limit_is_auto = bool(lim and lim.auto_generated)
    out.spent = spent
    out.left = (lim.amount - spent) if lim else None
    return out


def budgets_for_month(db: Session, month: str | None, active_only: bool = False) -> BudgetMonth:
    """Every budget for one month, plus spending without a budget. Commits filled-in amounts."""
    m, label = parse_month(month)
    q = select(Budget).order_by(func.lower(Budget.name))
    if active_only:
        q = q.where(Budget.active.is_(True))
    items = [budget_out(db, b, m, label) for b in db.scalars(q)]
    db.commit()
    unbudgeted = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.type == TransactionType.withdrawal.value,
            Transaction.budget_id.is_(None),
            Transaction.date >= m,
            Transaction.date < add_months(m, 1, 1),
        )
    )
    return BudgetMonth(
        month=label,
        budgets=items,
        budgeted=sum(b.limit or 0 for b in items if b.active),
        spent=sum(b.spent for b in items),
        unbudgeted_spent=int(unbudgeted or 0),
    )

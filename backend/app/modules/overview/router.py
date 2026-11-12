from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.dates import month_bounds
from ...db import get_db
from ..accounts.models import BALANCE_TYPES, Account
from ..accounts.service import account_out, account_stats
from ..auth.security import current_user
from ..budgets.service import budgets_for_month
from ..categories.models import Category
from ..transactions.models import Transaction, TransactionType
from ..transactions.service import txn_out
from .schemas import CategorySpend, Overview

router = APIRouter(tags=["overview"], dependencies=[Depends(current_user)])


@router.get("/overview", response_model=Overview)
def overview(month: str | None = None, db: Session = Depends(get_db)) -> Overview:
    """Balances right now, plus one month's income, spending and where it went."""
    try:
        start, end, label = month_bounds(month)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "month must look like YYYY-MM") from None

    balance_accounts = list(
        db.scalars(
            select(Account)
            .where(Account.type.in_([str(t) for t in BALANCE_TYPES]), Account.active.is_(True))
            .order_by(Account.type, func.lower(Account.name))
        )
    )
    stats = account_stats(db, [a.id for a in balance_accounts])
    accounts = [account_out(a, stats.get(a.id)) for a in balance_accounts]

    in_month = (Transaction.date >= start) & (Transaction.date < end)
    totals = {
        t: int(v or 0)
        for t, v in db.execute(
            select(Transaction.type, func.sum(Transaction.amount)).where(in_month).group_by(Transaction.type)
        )
    }

    cats = {c.id: c for c in db.scalars(select(Category))}
    by_category = []
    for cid, amount in db.execute(
        select(Transaction.category_id, func.sum(Transaction.amount))
        .where(in_month, Transaction.type == TransactionType.withdrawal.value)
        .group_by(Transaction.category_id)
        .order_by(func.sum(Transaction.amount).desc())
    ):
        c = cats.get(cid)
        by_category.append(
            CategorySpend(
                id=cid,
                name=c.name if c else "Uncategorised",
                icon=c.icon if c else "circle-help",
                color=c.color if c else "slate",
                amount=int(amount),
            )
        )

    budgets = [b for b in budgets_for_month(db, label, active_only=True).budgets if b.limit is not None or b.spent]
    recent = db.scalars(select(Transaction).order_by(Transaction.date.desc(), Transaction.id.desc()).limit(8)).unique()
    return Overview(
        month=label,
        net_worth=sum(a.balance for a in accounts),
        income=totals.get(TransactionType.deposit.value, 0),
        spending=totals.get(TransactionType.withdrawal.value, 0),
        accounts=accounts,
        by_category=by_category,
        recent=[txn_out(t) for t in recent],
        transaction_count=db.scalar(select(func.count(Transaction.id))) or 0,
        budgets=budgets,
    )

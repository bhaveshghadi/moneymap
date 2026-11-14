"""Balances and counterparty lookup."""

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..transactions.models import Transaction
from .models import OWN_TYPES, Account, AccountType
from .schemas import AccountOut


def account_stats(db: Session, account_ids: Iterable[int] | None = None) -> dict[int, dict]:
    """Per-account incoming/outgoing sums, transaction count and last activity date."""
    rows: dict[int, dict] = {}

    def acc(aid: int) -> dict:
        return rows.setdefault(aid, {"in": 0, "out": 0, "count": 0, "last": None})

    ids = list(account_ids) if account_ids is not None else None
    for side, col in (("in", Transaction.destination_id), ("out", Transaction.source_id)):
        q = select(col, func.coalesce(func.sum(Transaction.amount), 0), func.count(), func.max(Transaction.date))
        q = q.group_by(col)
        if ids is not None:
            q = q.where(col.in_(ids))
        for aid, total, count, last in db.execute(q):
            r = acc(aid)
            r[side] = int(total)
            r["count"] += count
            if last and (r["last"] is None or last > r["last"]):
                r["last"] = last
    return rows


def account_out(a: Account, stats: dict | None) -> AccountOut:
    st = stats or {"in": 0, "out": 0, "count": 0, "last": None}
    if a.type in OWN_TYPES:
        balance = a.opening_balance + st["in"] - st["out"]
    elif a.type == AccountType.expense:
        balance = st["in"]
    else:  # revenue
        balance = st["out"]
    out = AccountOut.model_validate(a)
    out.balance = balance
    out.transaction_count = st["count"]
    out.last_activity = st["last"]
    return out


def find_or_create_counterparty(db: Session, name: str, type_: AccountType) -> Account:
    """Expense/revenue account by name (case-insensitive), created if new."""
    name = name.strip()
    acct = db.scalar(select(Account).where(Account.type == type_, func.lower(Account.name) == name.lower()))
    if acct is None:
        acct = Account(name=name, type=type_, opening_balance=0, active=True)
        db.add(acct)
        db.flush()
    return acct

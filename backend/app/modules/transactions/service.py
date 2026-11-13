"""Transaction rules shared by the API (and later by recurring items and imports)."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..accounts.models import BALANCE_TYPES, Account, AccountType
from ..accounts.service import find_or_create_counterparty
from ..bills.models import Bill
from ..bills.service import match_bill
from ..budgets.models import Budget
from ..categories.models import Category, Tag
from .models import Transaction, TransactionType
from .schemas import TransactionIn, TransactionOut

# Which category kind fits which transaction type.
CATEGORY_KIND = {TransactionType.withdrawal: "expense", TransactionType.deposit: "income"}


def txn_out(t: Transaction) -> TransactionOut:
    return TransactionOut(
        id=t.id,
        type=t.type,
        date=t.date,
        amount=t.amount,
        description=t.description,
        source=t.source,  # type: ignore[arg-type]
        destination=t.destination,  # type: ignore[arg-type]
        category=t.category,  # type: ignore[arg-type]
        budget=t.budget,  # type: ignore[arg-type]
        bill=t.bill,  # type: ignore[arg-type]
        tags=sorted(tag.name for tag in t.tags),
        notes=t.notes,
    )


def _bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def _resolve_side(
    db: Session,
    account_id: int | None,
    name: str | None,
    allowed: set[str],
    counterparty: AccountType | None,
    label: str,
) -> Account:
    if account_id:
        a = db.get(Account, account_id)
        if a is None:
            raise _bad(f"{label} account not found")
    elif name and name.strip() and counterparty:
        a = find_or_create_counterparty(db, name, counterparty)
    else:
        raise _bad(f"{label} is required")
    if a.type not in allowed:
        raise _bad(f"{label} must be one of: {', '.join(sorted(allowed))} (got {a.type})")
    return a


def resolve_accounts(db: Session, body: TransactionIn) -> tuple[Account, Account]:
    """Check both sides for the transaction type, creating the payee account by name if needed."""
    balance = {str(x) for x in BALANCE_TYPES}
    if body.type == TransactionType.withdrawal:
        src = _resolve_side(db, body.source_id, None, balance, None, "Paid from")
        dst = _resolve_side(db, body.destination_id, body.destination_name, {"expense"}, AccountType.expense, "Paid to")
    elif body.type == TransactionType.deposit:
        src = _resolve_side(db, body.source_id, body.source_name, {"revenue"}, AccountType.revenue, "Received from")
        dst = _resolve_side(db, body.destination_id, None, balance, None, "Received in")
    else:
        src = _resolve_side(db, body.source_id, None, balance, None, "From")
        dst = _resolve_side(db, body.destination_id, None, balance, None, "To")
        if src.id == dst.id:
            raise _bad("A transfer needs two different accounts")
    return src, dst


def apply_body(db: Session, t: Transaction, body: TransactionIn, is_new: bool) -> None:
    """Fill `t` from the request body after validating it. `is_new` allows bill auto-matching."""
    src, dst = resolve_accounts(db, body)
    category_id = None
    # Categories describe spending/income; transfers between your own accounts stay uncategorised.
    if body.type != TransactionType.transfer and body.category_id is not None:
        cat = db.get(Category, body.category_id)
        if cat is None:
            raise _bad("Category not found")
        if cat.kind != CATEGORY_KIND[body.type]:
            raise _bad(f"'{cat.name}' is an {cat.kind} category")
        category_id = cat.id

    # Budgets only apply to expenses.
    budget_id = None
    if body.type == TransactionType.withdrawal and body.budget_id is not None:
        if db.get(Budget, body.budget_id) is None:
            raise _bad("Budget not found")
        budget_id = body.budget_id

    # Bills only apply to expenses; a new expense without one may be matched automatically.
    bill_id = None
    if body.type == TransactionType.withdrawal:
        if body.bill_id is not None:
            if db.get(Bill, body.bill_id) is None:
                raise _bad("Bill not found")
            bill_id = body.bill_id
        elif is_new and body.auto_match_bill:
            matched = match_bill(db, body.description, dst.name, body.amount)
            bill_id = matched.id if matched else None

    tags: list[Tag] = []
    for raw in sorted({n.strip() for n in body.tags if n.strip()}, key=str.lower):
        tag = db.scalar(select(Tag).where(func.lower(Tag.name) == raw.lower()))
        if tag is None:
            tag = Tag(name=raw[:64])
            db.add(tag)
        if tag not in tags:
            tags.append(tag)

    t.type = body.type.value
    t.date = body.date
    t.amount = body.amount
    t.description = body.description
    t.source_id = src.id
    t.destination_id = dst.id
    t.category_id = category_id
    t.budget_id = budget_id
    t.bill_id = bill_id
    t.notes = (body.notes or "").strip() or None
    t.tags = tags

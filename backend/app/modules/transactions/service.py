"""Transaction rules shared by the API (and later by recurring items and imports)."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..accounts.models import BALANCE_TYPES, Account, AccountType
from ..accounts.service import find_or_create_counterparty
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


def apply_body(db: Session, t: Transaction, body: TransactionIn) -> None:
    """Fill `t` from the request body after validating it."""
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
    t.notes = (body.notes or "").strip() or None
    t.tags = tags

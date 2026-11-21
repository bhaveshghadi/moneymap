from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from ...db import get_db
from ..accounts.models import Account
from ..auth.security import current_user
from ..budgets.models import BudgetCategory
from ..budgets.service import categories_of, in_budget
from ..categories.models import Category, Tag
from ..rules.engine import run_on_new
from .models import Transaction, TransactionType
from .schemas import BulkDeleteIn, BulkDeleteOut, TransactionIn, TransactionOut, TransactionPage
from .service import apply_body, reopen_statements, statements_of, sync_inbox_status, txn_out

router = APIRouter(prefix="/transactions", tags=["transactions"], dependencies=[Depends(current_user)])


def _filtered(
    q,
    *,
    db: Session,
    type_: TransactionType | None,
    account_id: int | None,
    category_id: int | None,
    uncategorised: bool,
    essential: bool | None,
    budget_id: int | None,
    no_budget: bool,
    bill_id: int | None,
    loan_id: int | None,
    tag: str | None,
    date_from: date | None,
    date_to: date | None,
    text: str | None,
):
    if type_:
        q = q.where(Transaction.type == type_.value)
    if account_id:
        q = q.where(or_(Transaction.source_id == account_id, Transaction.destination_id == account_id))
    if uncategorised:
        q = q.where(Transaction.category_id.is_(None), Transaction.type != TransactionType.transfer.value)
    elif category_id:
        q = q.where(Transaction.category_id == category_id)
    if essential is not None:  # spending in essential (or non-essential) expense categories
        cats = select(Category.id).where(Category.kind == "expense", Category.essential.is_(essential))
        q = q.where(Transaction.category_id.in_(cats), Transaction.type == TransactionType.withdrawal.value)
    if no_budget:
        q = q.where(Transaction.budget_id.is_(None), Transaction.type == TransactionType.withdrawal.value)
        counted = list(db.scalars(select(BudgetCategory.category_id)))  # categories a budget counts by itself
        if counted:
            q = q.where(or_(Transaction.category_id.is_(None), Transaction.category_id.not_in(counted)))
    elif budget_id:
        q = q.where(
            in_budget(budget_id, categories_of(db, budget_id)), Transaction.type == TransactionType.withdrawal.value
        )
    if bill_id:
        q = q.where(Transaction.bill_id == bill_id)
    if loan_id:  # a loan's EMIs, interest and money received (the loan's id, not its account's)
        q = q.where(Transaction.loan_id == loan_id)
    if tag:
        q = q.where(Transaction.tags.any(func.lower(Tag.name) == tag.lower()))
    if date_from:
        q = q.where(Transaction.date >= date_from)
    if date_to:
        q = q.where(Transaction.date <= date_to)
    # Plain text search: every word must appear in the description, the notes,
    # or either account's name (case-insensitive).
    for word in (text or "").lower().split()[:10]:
        like = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        src, dst = aliased(Account), aliased(Account)
        names = select(Transaction.id).join(src, Transaction.source_id == src.id)
        names = names.join(dst, Transaction.destination_id == dst.id)
        names = names.where(
            or_(func.lower(src.name).like(like, escape="\\"), func.lower(dst.name).like(like, escape="\\"))
        )
        q = q.where(
            or_(
                func.lower(Transaction.description).like(like, escape="\\"),
                func.lower(func.coalesce(Transaction.notes, "")).like(like, escape="\\"),
                Transaction.id.in_(names),
            )
        )
    return q


@router.get("", response_model=TransactionPage)
def list_transactions(
    type: TransactionType | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    uncategorised: bool = False,
    essential: bool | None = None,
    budget_id: int | None = None,
    no_budget: bool = False,
    bill_id: int | None = None,
    loan_id: int | None = None,
    tag: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> TransactionPage:
    """One page of transactions (newest first) plus totals for the whole filtered set."""
    f = dict(
        db=db,
        type_=type,
        account_id=account_id,
        category_id=category_id,
        uncategorised=uncategorised,
        essential=essential,
        budget_id=budget_id,
        no_budget=no_budget,
        bill_id=bill_id,
        loan_id=loan_id,
        tag=tag,
        date_from=date_from,
        date_to=date_to,
        text=q,
    )
    total = db.scalar(_filtered(select(func.count(Transaction.id)), **f)) or 0
    sums = dict(
        db.execute(
            _filtered(select(Transaction.type, func.sum(Transaction.amount)), **f).group_by(Transaction.type)
        ).all()
    )
    rows = db.scalars(
        _filtered(select(Transaction), **f)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    ).unique()
    return TransactionPage(
        items=[txn_out(t) for t in rows],
        total=total,
        sum_in=int(sums.get(TransactionType.deposit.value) or 0),
        sum_out=int(sums.get(TransactionType.withdrawal.value) or 0),
    )


def _get(db: Session, tid: int) -> Transaction:
    t = db.get(Transaction, tid)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    return t


@router.post("", response_model=TransactionOut, status_code=201)
def create_transaction(body: TransactionIn, db: Session = Depends(get_db)) -> TransactionOut:
    t = Transaction()
    apply_body(db, t, body, is_new=True)
    db.add(t)
    db.flush()
    db.refresh(t)
    run_on_new(db, t)  # rules fill only what you left empty
    sync_inbox_status(db, t.gmail_message_id)
    db.commit()
    db.refresh(t)
    return txn_out(t)


@router.post("/delete", response_model=BulkDeleteOut)
def delete_transactions(body: BulkDeleteIn, db: Session = Depends(get_db)) -> BulkDeleteOut:
    """Delete several transactions at once (the ones selected in the list). Each goes the same
    way as a single delete; ids that no longer exist are skipped."""
    found = list(db.scalars(select(Transaction).where(Transaction.id.in_(set(body.ids)))).unique())
    mids = [t.gmail_message_id for t in found]
    imports = statements_of(db, [t.id for t in found])
    for t in found:
        db.delete(t)
    sync_inbox_status(db, *mids)
    reopen_statements(db, imports)
    db.commit()
    return BulkDeleteOut(deleted=len(found))


@router.get("/{tid}", response_model=TransactionOut)
def get_transaction(tid: int, db: Session = Depends(get_db)) -> TransactionOut:
    return txn_out(_get(db, tid))


@router.put("/{tid}", response_model=TransactionOut)
def update_transaction(tid: int, body: TransactionIn, db: Session = Depends(get_db)) -> TransactionOut:
    t = _get(db, tid)
    before = t.gmail_message_id
    apply_body(db, t, body, is_new=False)
    sync_inbox_status(db, before, t.gmail_message_id)
    db.commit()
    db.refresh(t)
    return txn_out(t)


@router.delete("/{tid}", status_code=204)
def delete_transaction(tid: int, db: Session = Depends(get_db)) -> None:
    t = _get(db, tid)
    mid = t.gmail_message_id
    imports = statements_of(db, [t.id])
    db.delete(t)
    sync_inbox_status(db, mid)
    reopen_statements(db, imports)
    db.commit()

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.dates import month_bounds
from ...db import get_db
from ..auth.security import current_user
from ..transactions.models import Transaction, TransactionType, transaction_tag
from .models import Category, Tag
from .schemas import CategoryIn, CategoryOut, CategoryPatch, TagIn, TagOut

router = APIRouter(tags=["categories & tags"], dependencies=[Depends(current_user)])


def _commit_unique(db: Session, what: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"A {what} with that name already exists") from None


# ---------- categories ----------


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)) -> list[CategoryOut]:
    start, end, _ = month_bounds(None)
    counts = dict(db.execute(select(Transaction.category_id, func.count()).group_by(Transaction.category_id)).all())
    spent = dict(
        db.execute(
            select(Transaction.category_id, func.sum(Transaction.amount))
            .where(Transaction.type == TransactionType.withdrawal.value)
            .where(Transaction.date >= start, Transaction.date < end)
            .group_by(Transaction.category_id)
        ).all()
    )
    out = []
    for c in db.scalars(select(Category).order_by(Category.kind, func.lower(Category.name))):
        item = CategoryOut.model_validate(c)
        item.transaction_count = counts.get(c.id, 0)
        item.spent_this_month = int(spent.get(c.id) or 0)
        out.append(item)
    return out


def _get_cat(db: Session, cid: int) -> Category:
    c = db.get(Category, cid)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return c


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryIn, db: Session = Depends(get_db)) -> CategoryOut:
    c = Category(
        name=body.name.strip(),
        kind=body.kind,
        icon=body.icon,
        color=body.color,
        essential=body.essential and body.kind == "expense",
    )
    db.add(c)
    _commit_unique(db, "category")
    return CategoryOut.model_validate(c)


@router.patch("/categories/{cid}", response_model=CategoryOut)
def update_category(cid: int, body: CategoryPatch, db: Session = Depends(get_db)) -> CategoryOut:
    c = _get_cat(db, cid)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(c, k, v.strip() if k == "name" else v)
    if c.kind != "expense":
        c.essential = False  # only spending can be essential
    _commit_unique(db, "category")
    return CategoryOut.model_validate(c)


@router.delete("/categories/{cid}", status_code=204)
def delete_category(cid: int, db: Session = Depends(get_db)) -> None:
    """Transactions in this category become uncategorised (FK ondelete=SET NULL)."""
    db.delete(_get_cat(db, cid))
    db.commit()


# ---------- tags ----------


@router.get("/tags", response_model=list[TagOut])
def list_tags(db: Session = Depends(get_db)) -> list[TagOut]:
    counts = dict(db.execute(select(transaction_tag.c.tag_id, func.count()).group_by(transaction_tag.c.tag_id)).all())
    out = []
    for t in db.scalars(select(Tag).order_by(func.lower(Tag.name))):
        item = TagOut.model_validate(t)
        item.transaction_count = counts.get(t.id, 0)
        out.append(item)
    return out


def _get_tag(db: Session, tid: int) -> Tag:
    t = db.get(Tag, tid)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    return t


@router.post("/tags", response_model=TagOut, status_code=201)
def create_tag(body: TagIn, db: Session = Depends(get_db)) -> TagOut:
    t = Tag(name=body.name.strip())
    db.add(t)
    _commit_unique(db, "tag")
    return TagOut.model_validate(t)


@router.patch("/tags/{tid}", response_model=TagOut)
def rename_tag(tid: int, body: TagIn, db: Session = Depends(get_db)) -> TagOut:
    t = _get_tag(db, tid)
    t.name = body.name.strip()
    _commit_unique(db, "tag")
    return TagOut.model_validate(t)


@router.delete("/tags/{tid}", status_code=204)
def delete_tag(tid: int, db: Session = Depends(get_db)) -> None:
    db.delete(_get_tag(db, tid))
    db.commit()

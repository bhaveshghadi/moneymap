from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...db import get_db
from ..auth.security import current_user
from .models import Budget, BudgetLimit
from .schemas import BudgetIn, BudgetMonth, BudgetOut, BudgetPatch, LimitIn
from .service import budget_out, budgets_for_month, parse_month, reset_auto_limits, set_categories

router = APIRouter(prefix="/budgets", tags=["budgets"], dependencies=[Depends(current_user)])


@router.get("", response_model=BudgetMonth)
def list_budgets(month: str | None = None, db: Session = Depends(get_db)) -> BudgetMonth:
    """Every budget for one month (default: this month)."""
    return budgets_for_month(db, month)


def _get(db: Session, bid: int) -> Budget:
    b = db.get(Budget, bid)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Budget not found")
    return b


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A budget with that name already exists") from None


@router.post("", response_model=BudgetOut, status_code=201)
def create_budget(body: BudgetIn, month: str | None = None, db: Session = Depends(get_db)) -> BudgetOut:
    m, label = parse_month(month)
    b = Budget(name=body.name, active=body.active, mode=body.mode, amount=body.amount)
    db.add(b)
    _commit(db)
    if body.category_ids:
        set_categories(db, b, body.category_ids)
        db.commit()
    db.refresh(b)
    out = budget_out(db, b, m, label)
    db.commit()
    return out


@router.patch("/{bid}", response_model=BudgetOut)
def update_budget(bid: int, body: BudgetPatch, month: str | None = None, db: Session = Depends(get_db)) -> BudgetOut:
    m, label = parse_month(month)
    b = _get(db, bid)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "category_ids" in data:
        set_categories(db, b, data.pop("category_ids"))
    mode_changed = any(k in data and data[k] != getattr(b, k) for k in ("mode", "amount"))
    for k, v in data.items():
        setattr(b, k, v.strip() if k == "name" else v)
    if mode_changed:
        reset_auto_limits(db, b)
    _commit(db)
    out = budget_out(db, b, m, label)
    db.commit()
    return out


@router.put("/{bid}/limits/{month}", response_model=BudgetOut)
def set_limit(bid: int, month: str, body: LimitIn, db: Session = Depends(get_db)) -> BudgetOut:
    """Set one month's amount by hand (wins over fixed / rollover for that month)."""
    b = _get(db, bid)
    m, label = parse_month(month)
    lim = db.scalar(select(BudgetLimit).where(BudgetLimit.budget_id == b.id, BudgetLimit.month == m))
    if lim is None:
        db.add(BudgetLimit(budget_id=b.id, month=m, amount=body.amount, auto_generated=False))
    else:
        lim.amount = body.amount
        lim.auto_generated = False
    db.commit()
    out = budget_out(db, b, m, label)
    db.commit()
    return out


@router.delete("/{bid}/limits/{month}", response_model=BudgetOut)
def clear_limit(bid: int, month: str, db: Session = Depends(get_db)) -> BudgetOut:
    """Remove one month's amount (fixed / rollover budgets fill it in again)."""
    b = _get(db, bid)
    m, label = parse_month(month)
    lim = db.scalar(select(BudgetLimit).where(BudgetLimit.budget_id == b.id, BudgetLimit.month == m))
    if lim is not None:
        db.delete(lim)
        db.flush()
    out = budget_out(db, b, m, label)
    db.commit()
    return out


@router.delete("/{bid}", status_code=204)
def delete_budget(bid: int, db: Session = Depends(get_db)) -> None:
    """Expenses in this budget stay, without a budget."""
    db.delete(_get(db, bid))
    db.commit()

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db import get_db
from ..auth.security import current_user
from ..budgets.models import Budget, BudgetMode
from ..budgets.service import set_categories
from ..categories.models import Category
from .schemas import BudgetPicks, BudgetProposals, SavingsPlanOut, SavingsSettings
from .service import bad, budget_proposals, compute, get_settings, save_settings

router = APIRouter(prefix="/savings-plan", tags=["savings plan"], dependencies=[Depends(current_user)])


@router.get("", response_model=SavingsPlanOut)
def savings_plan(month: str | None = None, db: Session = Depends(get_db)) -> SavingsPlanOut:
    """One month (YYYY-MM, default this month) or `avg3` (the last 3 complete months, per month)."""
    return compute(db, month)


@router.get("/settings", response_model=SavingsSettings)
def read_settings(db: Session = Depends(get_db)) -> SavingsSettings:
    return get_settings(db)


@router.put("/settings", response_model=SavingsSettings)
def write_settings(body: SavingsSettings, db: Session = Depends(get_db)) -> SavingsSettings:
    return save_settings(db, body)


@router.get("/budgets", response_model=BudgetProposals)
def propose_budgets(db: Session = Depends(get_db)) -> BudgetProposals:
    """A budget for each want category, adding up to the wants share (nothing saved yet)."""
    return budget_proposals(db)


@router.post("/budgets", status_code=201)
def create_budgets(body: BudgetPicks, db: Session = Depends(get_db)) -> dict:
    """Make the budgets you ticked: a fixed amount a month, counting the category by itself."""
    names = {n.lower() for n in db.scalars(select(Budget.name))}
    made = []
    for pick in body.items:
        c = db.get(Category, pick.category_id)
        if c is None or c.kind != "expense":
            raise bad("Pick expense categories only.")
        name = (pick.name or c.name).strip()[:80]
        base, n = name, 2
        while name.lower() in names:
            name = f"{base} ({n})"[:80]
            n += 1
        names.add(name.lower())
        b = Budget(name=name, active=True, mode=BudgetMode.fixed, amount=pick.amount)
        db.add(b)
        db.flush()
        set_categories(db, b, [c.id])
        made.append({"id": b.id, "name": b.name, "amount": b.amount, "category_id": c.id})
    db.commit()
    if not made:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to make.")
    return {"created": made, "count": db.scalar(select(func.count(Budget.id)))}

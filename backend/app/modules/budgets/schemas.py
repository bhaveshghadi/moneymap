from pydantic import BaseModel, Field, field_validator

from ...core.schemas import ORM
from .models import BudgetMode


class BudgetIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    active: bool = True
    mode: BudgetMode = BudgetMode.manual
    amount: int = Field(default=0, ge=0, le=10**13)  # paise per month (fixed / rollover)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class BudgetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    active: bool | None = None
    mode: BudgetMode | None = None
    amount: int | None = Field(default=None, ge=0, le=10**13)


class LimitIn(BaseModel):
    amount: int = Field(ge=0, le=10**13)


class BudgetOut(ORM):
    id: int
    name: str
    active: bool
    mode: str
    amount: int
    month: str = ""  # YYYY-MM this row describes
    limit: int | None = None  # None = no amount for this month
    limit_is_auto: bool = False  # filled in from the mode (not set by hand)
    spent: int = 0
    left: int | None = None


class BudgetMonth(BaseModel):
    month: str
    budgets: list[BudgetOut]
    budgeted: int  # total amount of active budgets this month
    spent: int  # spent in budgets this month
    unbudgeted_spent: int  # expenses this month with no budget

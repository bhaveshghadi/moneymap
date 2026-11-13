from datetime import date as Date

from pydantic import BaseModel, Field, field_validator, model_validator

from ...core.schemas import ORM
from .models import BillRepeat


class BillIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount_min: int = Field(gt=0, le=10**13)  # paise
    amount_max: int = Field(gt=0, le=10**13)
    first_due: Date
    repeat: BillRepeat = BillRepeat.monthly
    skip: int = Field(default=0, ge=0, le=12)  # 1 = every other period
    match: str | None = Field(default=None, max_length=255)  # comma-separated words
    active: bool = True
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v

    @model_validator(mode="after")
    def _range(self) -> "BillIn":
        if self.amount_max < self.amount_min:
            raise ValueError("Maximum amount must be at least the minimum")
        return self


class BillOut(ORM):
    id: int
    name: str
    amount_min: int
    amount_max: int
    first_due: Date
    repeat: str
    skip: int
    match: str | None
    active: bool
    notes: str | None
    next_due: Date | None = None
    status: str = "upcoming"  # paid | due_soon | overdue | upcoming | inactive
    last_paid_date: Date | None = None
    last_paid_amount: int | None = None
    monthly_cost: int = 0  # average amount spread over a month
    transaction_count: int = 0


class BillDue(BaseModel):
    bill_id: int
    name: str
    due: Date
    status: str
    expected: int  # average of the amount range

from datetime import date as Date

from pydantic import BaseModel, Field, field_validator

from ...core.schemas import ORM
from ..accounts.schemas import AccountRef
from ..categories.schemas import CategoryRef
from .models import TransactionType


class TransactionIn(BaseModel):
    type: TransactionType
    date: Date
    amount: int = Field(gt=0, le=10**13)  # paise; up to ₹10,000 crore
    description: str = Field(min_length=1, max_length=255)
    # Either an existing account id, or (for the expense/revenue side) a
    # payee name that is looked up or created.
    source_id: int | None = None
    source_name: str | None = Field(default=None, max_length=120)
    destination_id: int | None = None
    destination_name: str | None = Field(default=None, max_length=120)
    category_id: int | None = None
    budget_id: int | None = None  # expenses only; ignored for income and transfers
    tags: list[str] = []
    notes: str | None = None

    @field_validator("description")
    @classmethod
    def _desc(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Description is required")
        return v


class NamedRef(ORM):
    id: int
    name: str


class TransactionOut(ORM):
    id: int
    type: str
    date: Date
    amount: int
    description: str
    source: AccountRef
    destination: AccountRef
    category: CategoryRef | None
    budget: NamedRef | None = None
    tags: list[str]
    notes: str | None


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    sum_in: int  # income in the filtered set
    sum_out: int  # expenses in the filtered set

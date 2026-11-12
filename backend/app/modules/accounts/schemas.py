from datetime import date as Date

from pydantic import BaseModel, Field, field_validator

from ...core.schemas import ORM
from .models import AccountType


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: AccountType
    account_number: str | None = Field(default=None, max_length=64)
    opening_balance: int = 0
    opening_date: Date | None = None
    active: bool = True
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: AccountType | None = None  # only between bank (asset) and cash
    account_number: str | None = Field(default=None, max_length=64)
    opening_balance: int | None = None
    opening_date: Date | None = None
    active: bool | None = None
    notes: str | None = None


class AccountRef(ORM):
    id: int
    name: str
    type: str


class AccountOut(ORM):
    id: int
    name: str
    type: str
    account_number: str | None
    opening_balance: int
    opening_date: Date | None
    active: bool
    notes: str | None
    # Bank/cash: current balance. Expense: total spent there. Revenue: total received.
    balance: int = 0
    transaction_count: int = 0
    last_activity: Date | None = None

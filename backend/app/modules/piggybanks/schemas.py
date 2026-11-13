from datetime import date as Date

from pydantic import BaseModel, Field, field_validator

from ...core.schemas import ORM
from ..accounts.schemas import AccountRef


class PiggyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    account_id: int
    target_amount: int = Field(gt=0, le=10**13)  # paise
    target_date: Date | None = None
    active: bool = True
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class PiggyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    account_id: int | None = None
    target_amount: int | None = Field(default=None, gt=0, le=10**13)
    target_date: Date | None = None  # send null to remove the target date
    active: bool | None = None
    notes: str | None = None


class PiggyEventIn(BaseModel):
    amount: int = Field(ge=-(10**13), le=10**13)  # paise: + set aside, − take out; never 0
    date: Date | None = None  # default: today
    note: str | None = Field(default=None, max_length=255)


class PiggyEventOut(ORM):
    id: int
    date: Date
    amount: int
    note: str | None


class PiggyOut(ORM):
    id: int
    name: str
    account: AccountRef
    target_amount: int
    target_date: Date | None
    active: bool
    notes: str | None
    saved: int = 0
    account_balance: int = 0
    account_available: int = 0  # the account's balance not yet set aside in any piggy bank
    monthly_needed: int | None = None  # to reach the target by the target date

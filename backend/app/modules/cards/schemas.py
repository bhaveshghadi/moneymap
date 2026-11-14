from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .emi import EmiOut

DueMode = Literal["days_after", "fixed_day"]
CycleStatus = Literal["unbilled", "nothing_due", "billed", "partly_paid", "paid", "overdue"]
Network = Literal["visa", "mastercard", "rupay", "amex", "diners", "other"]


class CardIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    bank: str | None = Field(default=None, max_length=80)
    last4: str | None = None
    network: Network | None = None
    credit_limit: int = Field(default=0, ge=0, le=10**13)  # paise
    statement_day: int = Field(ge=1, le=31)
    due_mode: DueMode = "days_after"
    due_value: int = Field(default=20, ge=1, le=60)  # days (1-60) or day of month (1-31)
    min_due_pct: int = Field(default=5, ge=1, le=100)
    color: str = Field(default="indigo", max_length=16)
    opening_owed: int = Field(default=0, ge=0, le=10**13)  # owed on the card when you start tracking it
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

    @field_validator("last4")
    @classmethod
    def _last4(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if not v:
            return None
        if not (len(v) == 4 and v.isdigit()):
            raise ValueError("Last 4 digits must be 4 numbers")
        return v


class CardPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    bank: str | None = Field(default=None, max_length=80)
    last4: str | None = None
    network: Network | None = None
    credit_limit: int | None = Field(default=None, ge=0, le=10**13)
    statement_day: int | None = Field(default=None, ge=1, le=31)
    due_mode: DueMode | None = None
    due_value: int | None = Field(default=None, ge=1, le=60)
    min_due_pct: int | None = Field(default=None, ge=1, le=100)
    color: str | None = Field(default=None, max_length=16)
    opening_owed: int | None = Field(default=None, ge=0, le=10**13)
    opening_date: Date | None = None
    active: bool | None = None
    notes: str | None = None

    _last4 = field_validator("last4")(CardIn._last4.__func__)  # type: ignore[attr-defined]


class CycleOut(BaseModel):
    start: Date
    statement_date: Date
    due_date: Date
    spent: int
    credits: int
    total_due: int
    min_due: int
    paid: int
    paid_on: Date | None
    status: CycleStatus
    min_paid: bool
    official: bool = False  # figures from the imported statement


class CardOut(BaseModel):
    id: int  # the card's account id (used in transactions)
    name: str
    bank: str | None
    last4: str | None
    network: str | None
    color: str
    credit_limit: int
    min_due_pct: int
    statement_day: int
    due_mode: DueMode
    due_value: int
    opening_owed: int
    opening_date: Date | None
    active: bool
    notes: str | None
    owed: int  # outstanding on the card right now (EMI principal not yet billed is in emi_outstanding)
    emi_outstanding: int = 0  # EMI principal still to pay (not on a bill yet)
    emi_count: int = 0  # active EMIs
    available: int | None  # limit − owed − EMI outstanding (None without a limit)
    utilisation: float | None  # % of the limit used, EMIs included
    current: CycleOut  # the open (unbilled) cycle
    last_statement: CycleOut | None  # the latest closed cycle
    due_now: int  # still to pay on the latest statement
    next_due_date: Date | None  # its due date (the oldest missed one when overdue), while something is due
    due_status: CycleStatus | None  # billed / partly_paid / overdue while something is due
    best_swipe_day: Date  # the day after the next statement date — the longest interest-free time
    interest_free_days: int  # from best_swipe_day to that cycle's due date
    transaction_count: int


class CardDetail(CardOut):
    cycles: list[CycleOut]  # newest first (the open cycle first)
    emis: list[EmiOut] = []


class Convertible(BaseModel):
    """An expense that looks like a card bill payment (CRED, 'credit card payment', or a
    card category) — it should be a transfer bank -> card."""

    transaction_id: int
    date: Date
    amount: int
    description: str
    paid_from: str
    payee: str
    category: str | None
    suggested_card_id: int | None
    why: str | None


class ConvertItem(BaseModel):
    transaction_id: int
    card_id: int


class ConvertIn(BaseModel):
    items: list[ConvertItem] = Field(min_length=1, max_length=500)


class EmptyCategory(BaseModel):
    id: int
    name: str


class ConvertOut(BaseModel):
    converted: int
    empty_categories: list[EmptyCategory]  # card-bill categories with no transactions left (safe to delete)


class CardDue(BaseModel):
    """The Overview: a card statement still to pay."""

    card_id: int
    name: str
    last4: str | None
    due_date: Date
    amount: int  # still to pay
    min_due: int
    status: CycleStatus

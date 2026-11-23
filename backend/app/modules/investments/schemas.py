from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, Field

from ..transactions.schemas import TransactionOut

Kind = Literal[
    "mf",
    "fd",
    "rd",
    "post_office",
    "retirement",
    "insurance",
    "lent",
    "chit",
    "gold",
    "stocks",
    "crypto",
    "property",
    "other",
]
Compounding = Literal["monthly", "quarterly", "half_yearly", "yearly", "payout", "simple"]
Frequency = Literal["monthly", "quarterly", "half_yearly", "yearly", "single"]


class _Terms(BaseModel):
    subtype: str | None = Field(default=None, max_length=16)
    institution: str | None = Field(default=None, max_length=120)
    number: str | None = Field(default=None, max_length=64)
    person: str | None = Field(default=None, max_length=120)
    rate: float | None = Field(default=None, ge=0, le=100)  # yearly %
    compounding: Compounding | None = None
    start_date: Date | None = None
    maturity_date: Date | None = None
    months: int | None = Field(default=None, ge=1, le=1200)
    instalment: int | None = Field(default=None, gt=0)  # paise
    frequency: Frequency | None = None
    sum_assured: int | None = Field(default=None, ge=0)
    maturity_amount: int | None = Field(default=None, ge=0)
    quantity: float | None = Field(default=None, gt=0)  # grams / units / shares
    purity: str | None = Field(default=None, max_length=8)
    unit_price: int | None = Field(default=None, ge=0)  # paise per unit
    current_value: int | None = None  # paise
    value_date: Date | None = None
    payout_on: Date | None = None
    payout_amount: int | None = Field(default=None, ge=0)
    pay_from_id: int | None = None
    notes: str | None = None


class FundIn(BaseModel):
    """A mutual fund added by hand (picked from the AMFI scheme list)."""

    scheme: str = Field(min_length=1, max_length=255)
    isin: str | None = Field(default=None, max_length=12)
    amc: str | None = Field(default=None, max_length=120)
    folio: str | None = Field(default=None, max_length=40)
    amfi_code: str | None = Field(default=None, max_length=12)
    nav: int | None = Field(default=None, gt=0)  # 1/10000 rupee
    nav_date: Date | None = None


class FundOut(BaseModel):
    scheme: str
    amc: str | None
    isin: str | None
    folio: str | None
    units: float
    units_as_of: Date | None
    nav: float | None  # rupees
    nav_date: Date | None
    nav_source: str | None
    cost: int | None  # paise, from the CAS


class FundTxnOut(BaseModel):
    id: int
    date: Date
    kind: str
    kind_label: str
    description: str
    amount: int
    units: float
    nav: float
    stamp_duty: int
    transaction_id: int | None


class InvestmentIn(_Terms):
    kind: Kind
    name: str | None = Field(default=None, max_length=120)
    amount: int | None = Field(default=None, gt=0)  # paise put in (not for RD / insurance / chit)
    money: Literal["bank", "already"] = "already"
    fund: FundIn | None = None  # mutual fund by hand  # bank = record a transfer from pay_from_id


class InvestmentPatch(_Terms):
    name: str | None = Field(default=None, max_length=120)
    amount: int | None = Field(default=None, ge=0)  # the amount already invested before tracking (opening)
    closed_on: Date | None = None


class DueOut(BaseModel):
    account_id: int
    name: str
    kind: str
    date: Date
    what: str  # matures | premium | due_back | instalment | balance (property: a planned payment)
    amount: int
    overdue: bool = False


PropertyStatus = Literal["booked", "agreement", "registration_pending", "registered"]
CostKind = Literal["stamp_duty", "registration", "legal", "broker", "other"]


class InstalmentIn(BaseModel):
    due_date: Date
    amount: int = Field(gt=0, le=10**13)
    note: str | None = Field(default=None, max_length=120)


class PropertyIn(BaseModel):
    price: int | None = Field(default=None, gt=0, le=10**13)  # paise: total agreed price
    size: str | None = Field(default=None, max_length=60)
    location: str | None = Field(default=None, max_length=200)
    survey_no: str | None = Field(default=None, max_length=60)
    seller: str | None = Field(default=None, max_length=120)
    agreement_date: Date | None = None
    status: PropertyStatus = "agreement"
    registered_on: Date | None = None
    plan: list[InstalmentIn] = []  # replaces the plan


class CostIn(BaseModel):
    kind: CostKind
    amount: int = Field(gt=0, le=10**13)
    date: Date
    bank_id: int | None = None  # paid from this account now (a transfer into the property); None = paid already
    note: str | None = Field(default=None, max_length=120)


class GoalIn(BaseModel):
    account_id: int  # the bank / cash account the money is set aside in


class InstalmentOut(BaseModel):
    id: int
    due_date: Date
    amount: int
    note: str | None
    paid: int  # of this instalment, from the money paid so far (oldest first)
    status: Literal["paid", "part", "due", "overdue"]


class CostOut(BaseModel):
    id: int
    kind: CostKind
    amount: int
    date: Date
    note: str | None
    transaction_id: int | None


class PropertyOut(BaseModel):
    price: int | None
    size: str | None
    location: str | None
    survey_no: str | None
    seller: str | None
    agreement_date: Date | None
    status: PropertyStatus
    registered_on: Date | None
    price_paid: int  # paid toward the price (money in, less costs paid through MoneyMap)
    balance: int | None  # price − price paid; None without a price
    costs_total: int
    total_cost: int  # price paid + costs: what it has cost so far
    plan: list[InstalmentOut]
    unplanned: int | None  # balance not covered by the plan
    costs: list[CostOut]
    goal_id: int | None
    goal_saved: int | None  # set aside in the goal


class InvestmentOut(BaseModel):
    id: int  # account id
    name: str
    kind: str
    subtype: str | None
    institution: str | None
    number: str | None
    person: str | None
    rate: float | None
    compounding: str | None  # as used (defaults filled in)
    start_date: Date | None
    maturity_date: Date | None  # as used (RD: start + months)
    months: int | None
    instalment: int | None
    frequency: str | None
    sum_assured: int | None
    maturity_amount: int | None
    quantity: float | None
    purity: str | None
    unit_price: int | None
    current_value: int | None
    payout_on: Date | None
    payout_amount: int | None
    pay_from_id: int | None
    opening: int  # amount already invested before tracking
    closed_on: Date | None
    notes: str | None
    status: Literal["active", "closed"]
    money_in: int
    money_out: int
    invested: int  # money in - money out
    value: int  # today (0 once closed; negative = a chit's instalments still owed)
    gain: int
    gain_pct: float | None
    value_date: Date | None  # the date the value is from
    maturity_value: int | None
    paid_count: int | None
    total_count: int | None
    owed: int
    stale: bool  # a value entered by hand, over 90 days old
    no_price: bool  # no price / rate yet: value shown = invested
    next_due: DueOut | None
    fund: FundOut | None = None
    property: PropertyOut | None = None  # mutual funds


class InvestmentDetail(InvestmentOut):
    moves: list[TransactionOut]  # money in and out, newest first
    fund_txns: list[FundTxnOut] = []  # mutual funds: unit movements from the CAS, newest first


class RatesIO(BaseModel):
    gold_24k: int | None = Field(default=None, ge=0)  # paise per gram
    silver: int | None = Field(default=None, ge=0)  # paise per gram (999)
    date: Date | None = None


class KindTotal(BaseModel):
    kind: str
    count: int
    invested: int
    value: int


class InvestmentSummary(BaseModel):
    invested: int
    value: int
    gain: int
    owed: int  # chit instalments still to pay after the payout
    count: int
    by_kind: list[KindTotal]
    dues: list[DueOut]  # next 30 days + matured / overdue
    rates: RatesIO


class MoveIn(BaseModel):
    direction: Literal["in", "out"]
    amount: int = Field(gt=0)
    date: Date
    bank_id: int
    description: str | None = Field(default=None, max_length=200)


class Linkable(BaseModel):
    """A bank / cash expense or income that may be money into or out of this investment."""

    transaction_id: int
    date: Date
    amount: int
    direction: Literal["in", "out"]  # in = from your bank into the investment
    description: str
    account: str  # the bank / cash account
    counterparty: str
    category: str | None
    suggested: bool
    why: str | None


class LinkIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    lower_opening: bool = False  # these payments were part of "already invested before tracking"


class LinkOut(BaseModel):
    linked: int
    investment: "InvestmentDetail"


class CloseIn(BaseModel):
    date: Date
    amount: int | None = Field(default=None, gt=0)  # money received on closing, into bank_id
    bank_id: int | None = None

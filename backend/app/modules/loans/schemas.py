from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Method = Literal["reducing", "flat", "emi_only"]
CountMode = Literal["whole_emi", "interest_only"]
FirstInterest = Literal["month", "days365", "days360"]
Kind = Literal["home", "car", "two_wheeler", "personal", "education", "gold", "property", "consumer", "other"]


class LoanIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    lender: str | None = Field(default=None, max_length=120)
    kind: Kind = "personal"
    loan_number: str | None = Field(default=None, max_length=32)
    method: Method = "reducing"
    count_mode: CountMode = "whole_emi"
    principal: int | None = Field(default=None, gt=0, le=10**13)  # paise
    rate: float | None = Field(default=None, ge=0, le=60)  # % a year
    tenure: int = Field(ge=1, le=600)
    emi: int | None = Field(default=None, gt=0, le=10**12)  # paise; empty = worked out
    first_emi_date: Date
    disbursed_date: Date | None = None
    first_interest: FirstInterest = "month"  # EMI 1: a month's interest, or the days since disbursed_date
    pay_from_id: int | None = None
    start: Literal["new", "existing"] = "new"
    # new loan: where the money went
    money: Literal["received", "seller", "none"] = "none"
    received_into_id: int | None = None  # money == received: the bank account it came into
    seller_name: str | None = Field(default=None, max_length=120)  # money == seller (interest_only)
    category_id: int | None = None  # money == seller (interest_only): what it paid for
    # existing loan
    paid_before: int | None = Field(default=None, ge=0, le=600)  # EMIs paid before tracking (empty = by date)
    link_ids: list[int] = []  # past "Loan / EMI" expenses to move onto the loan
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class LoanPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    lender: str | None = Field(default=None, max_length=120)
    kind: Kind | None = None
    loan_number: str | None = Field(default=None, max_length=32)
    pay_from_id: int | None = None
    notes: str | None = None
    closed_on: Date | None = None
    # terms: the schedule is worked out again; recorded EMIs keep their amounts
    method: Method | None = None
    count_mode: CountMode | None = None  # changing it re-records the linked EMIs the other way
    principal: int | None = Field(default=None, gt=0, le=10**13)
    rate: float | None = Field(default=None, ge=0, le=60)
    tenure: int | None = Field(default=None, ge=1, le=600)
    emi: int | None = Field(default=None, gt=0, le=10**12)  # null with new terms = worked out again
    first_emi_date: Date | None = None
    disbursed_date: Date | None = None
    first_interest: FirstInterest | None = None
    paid_before: int | None = Field(default=None, ge=0, le=600)


class EventOut(BaseModel):
    id: int
    kind: str  # prepay | rate
    date: Date
    mode: str  # reduce_tenure | reduce_emi
    amount: int | None
    rate: float | None
    before_n: int | None  # applies before this EMI
    emi_after: int | None
    txn_id: int | None


class PrepayIn(BaseModel):
    date: Date
    amount: int = Field(gt=0, le=10**13)
    mode: Literal["reduce_tenure", "reduce_emi"] = "reduce_tenure"
    from_account_id: int | None = None  # default: the loan's "paid from" account
    transaction_id: int | None = None  # an existing expense that IS this part-payment (e.g. from a statement)
    fee: int | None = Field(default=None, gt=0, le=10**12)  # the lender's part-payment / closing charge


class RateIn(BaseModel):
    date: Date
    rate: float = Field(ge=0, le=60)
    mode: Literal["reduce_tenure", "reduce_emi"] = "reduce_tenure"


class EventPatch(BaseModel):
    mode: Literal["reduce_tenure", "reduce_emi"]


class WhatIfIn(BaseModel):
    kind: Literal["prepay", "rate"] = "prepay"
    date: Date | None = None  # default: today
    amount: int | None = Field(default=None, gt=0, le=10**13)
    rate: float | None = Field(default=None, ge=0, le=60)
    mode: Literal["reduce_tenure", "reduce_emi"] = "reduce_tenure"


class PlanOut(BaseModel):
    emi: int
    months: int
    interest: int
    end_date: Date | None


class WhatIfOut(BaseModel):
    outstanding: int
    before: PlanOut
    after: PlanOut
    interest_saved: int  # negative = extra interest (e.g. a higher rate)
    months_saved: int
    paid_off: bool


class RowOut(BaseModel):
    n: int
    date: Date
    emi: int
    principal: int
    interest: int
    balance: int
    paid: bool


class NextEmi(BaseModel):
    n: int
    date: Date
    emi: int
    principal: int
    interest: int
    overdue: bool


class LoanOut(BaseModel):
    id: int  # the loan's account id
    loan_id: int
    name: str
    lender: str | None
    kind: str
    loan_number: str | None
    method: str
    count_mode: str
    principal: int | None
    rate: float | None  # % a year at the start (worked out for emi_only with an amount)
    current_rate: float | None  # after rate changes so far
    rate_worked_out: bool
    tenure: int
    emi: int  # at the start
    current_emi: int  # after part-payments / rate changes
    first_emi_date: Date
    disbursed_date: Date | None
    first_interest: str  # month | days365 | days360
    first_interest_days: int | None  # days counted in EMI 1 (days365 / days360 with a taken-on date)
    last_emi_off: bool = False  # the last EMI is > 2% away from the EMI (reducing, no changes)
    first_interest_suggestion: str | None = None  # the first-EMI interest that makes it fit
    end_date: Date
    pay_from_id: int | None
    pay_from_name: str | None
    paid_before: int
    paid_count: int
    prepaid: int  # part-payments so far
    outstanding: int  # principal still to pay (emi_only without an amount: EMIs still to pay)
    total_interest: int
    total_payable: int
    interest_paid: int
    next: NextEmi | None
    status: str  # active | closed
    closed_on: Date | None
    notes: str | None
    supports_changes: bool  # part-payments / rate changes (reducing balance only)
    events: list[EventOut] = []


class LoanDetail(LoanOut):
    schedule: list[RowOut]


class PayIn(BaseModel):
    date: Date | None = None  # default: the EMI's date
    from_account_id: int | None = None  # default: the loan's "paid from" account


class Linkable(BaseModel):
    transaction_id: int
    date: Date
    amount: int
    description: str
    paid_from: str
    category: str | None
    emi_like: bool  # the amount matches the EMI (other amounts: part-payments, next phase)
    suggested: bool  # looks like this loan's EMI (amount, loan number or lender)


class LinkIn(BaseModel):
    transaction_ids: list[int] = Field(min_length=1, max_length=600)


class LinkOut(BaseModel):
    linked: int
    loan: LoanDetail


class LoanDue(BaseModel):
    """The Overview: the next EMI of a loan, overdue or within the next 30 days."""

    loan_id: int  # account id
    name: str
    date: Date
    amount: int
    n: int
    tenure: int
    overdue: bool

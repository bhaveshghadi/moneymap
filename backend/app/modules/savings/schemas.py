from typing import Literal

from pydantic import BaseModel, Field, model_validator

RuleName = Literal["50_30_20", "60_20_20", "70_20_10", "80_20", "custom"]
Basis = Literal["actual", "avg3", "fixed"]

# needs / wants / savings in %; None for needs and wants = one "spending" share (80/20: pay yourself first)
PRESETS: dict[str, tuple[int | None, int | None, int]] = {
    "50_30_20": (50, 30, 20),
    "60_20_20": (60, 20, 20),
    "70_20_10": (70, 20, 10),
    "80_20": (None, None, 20),
}


class SavingsSettings(BaseModel):
    rule: RuleName = "50_30_20"
    needs: int | None = Field(default=50, ge=0, le=100)
    wants: int | None = Field(default=30, ge=0, le=100)
    savings: int = Field(default=20, ge=0, le=100)
    basis: Basis = "actual"  # the income the shares are of: the month's own, the 3-month average, or a fixed take-home
    fixed_income: int | None = Field(default=None, ge=0, le=10**13)  # paise a month

    @model_validator(mode="after")
    def _shares(self) -> "SavingsSettings":
        if self.rule != "custom":
            self.needs, self.wants, self.savings = PRESETS[self.rule]
        elif self.needs is None or self.wants is None or self.needs + self.wants + self.savings != 100:
            raise ValueError("Needs, wants and savings must add up to 100%.")
        if self.basis == "fixed" and not self.fixed_income:
            raise ValueError("Enter your monthly take-home pay to use it as the income.")
        return self


class Share(BaseModel):
    amount: int  # paise in the period (a month, or the 3-month average)
    pct: float | None  # of the income used; None with no income
    target_pct: int | None  # None: not judged on its own (80/20)
    target: int | None  # paise
    diff: int | None  # amount − target: + over (needs / wants), − short (savings)


class Line(BaseModel):
    category_id: int | None
    name: str
    icon: str
    color: str
    amount: int
    before: int | None = None  # the average of the 3 months before (for "grew")


class SavingsSplit(BaseModel):
    to_investments: int  # moved into investments (transfers in − money taken out, + "Investment" expenses)
    to_goals: int  # set aside in piggy banks and the emergency fund
    left_in_bank: int  # the rest (negative: more spent than came in)


class Suggestion(BaseModel):
    kind: Literal[
        "no_income", "wants_over", "needs_over", "spending_over", "emi_high", "save_more", "emergency_first",
        "invest_extra", "uncategorised", "on_track",
    ]  # fmt: skip
    tone: Literal["warn", "info", "good"]
    title: str
    detail: str = ""
    amount: int | None = None
    items: list[Line] = []  # e.g. categories to trim, with `amount` = how much to cut


class SavingsPlanOut(BaseModel):
    settings: SavingsSettings
    period: str  # "YYYY-MM" or "avg3"
    period_label: str
    months: int  # 1, or 3 for the average
    period_start: str
    period_end: str  # first day after
    income: int  # money that came in during the period (per month)
    income_used: int  # the income the shares are of (per the basis)
    needs: Share
    wants: Share
    spending: Share  # needs + wants together (what 80/20 judges)
    savings: Share
    savings_split: SavingsSplit
    needs_lines: list[Line]  # essential categories, loan EMIs
    wants_lines: list[Line]
    uncategorised: int  # in wants
    emi_monthly: int  # EMIs of active loans
    suggestions: list[Suggestion]


class BudgetProposal(BaseModel):
    category_id: int
    name: str
    icon: str
    color: str
    average: int  # per month over the last 3 complete months
    amount: int  # proposed monthly budget
    budget_name: str | None = None  # already counted by this budget (left out of the proposal)


class BudgetProposals(BaseModel):
    wants_target: int  # what the wants share allows a month
    total_average: int
    items: list[BudgetProposal]
    taken: list[BudgetProposal]  # categories already in a budget


class BudgetPick(BaseModel):
    category_id: int
    amount: int = Field(gt=0, le=10**13)
    name: str | None = Field(default=None, max_length=80)


class BudgetPicks(BaseModel):
    items: list[BudgetPick] = Field(min_length=1)

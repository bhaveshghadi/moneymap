from typing import Literal

from pydantic import BaseModel, Field

from ..piggybanks.schemas import PiggyOut

EmergencyStatus = Literal["not_set_up", "no_data", "low", "building", "safe", "done"]
MonthlySource = Literal["median", "estimate", "override", "none"]


class EmergencyIn(BaseModel):
    account_id: int  # bank or cash account that holds the money
    months_cover: int = Field(default=6, ge=1, le=60)  # up to 5 years
    average_months: Literal[3, 6, 12] = 6
    monthly_override: int | None = Field(default=None, ge=0, le=10**13)  # paise; null = calculate


class EmergencyMonth(BaseModel):
    month: str  # YYYY-MM
    amount: int  # essential spending that month (paise)


class EmergencyEstimate(BaseModel):
    """The typical month for one averaging window, so the settings can preview any choice live."""

    average_months: int  # 3, 6 or 12
    monthly: int  # paise
    source: MonthlySource  # median, estimate (< 3 months of history) or none
    months_of_data: int


class EmergencyOut(BaseModel):
    configured: bool
    piggy: PiggyOut | None = None
    months_cover: int = 6
    average_months: int = 6
    monthly_override: int | None = None
    monthly_essential: int = 0  # the typical month used for the target
    monthly_source: MonthlySource = "none"  # median of the months, an estimate (< 3 months), your amount, or none
    months_of_data: int = 0  # complete months with history that were used
    history: list[EmergencyMonth] = []  # oldest first
    essential_categories: list[str] = []
    estimates: list[EmergencyEstimate] = []  # typical month for each averaging window (3, 6, 12)
    target: int = 0
    saved: int = 0
    covered_months: float | None = None  # saved ÷ typical month
    status: EmergencyStatus = "not_set_up"
    monthly_to_save: int | None = None  # to reach the target by the piggy bank's target date


class EmergencySummary(BaseModel):
    """The Overview card."""

    target: int
    saved: int
    months_cover: int
    covered_months: float | None
    status: EmergencyStatus

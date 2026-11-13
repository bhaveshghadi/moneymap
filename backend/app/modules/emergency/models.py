from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from ...db import Base


class EmergencyFund(Base):
    """Settings for the emergency fund (at most one row). The money itself is a
    special piggy bank, whose target follows the essential spending."""

    __tablename__ = "emergency_fund"
    id: Mapped[int] = mapped_column(primary_key=True)
    # The piggy bank holding the money; NULL once that piggy bank is deleted (fund switched off).
    piggy_id: Mapped[int | None] = mapped_column(
        ForeignKey("piggy_bank.id", ondelete="SET NULL", name="fk_emergency_fund_piggy_id_piggy_bank")
    )
    months_cover: Mapped[int] = mapped_column(Integer, default=6)  # months of essential spending to keep
    average_months: Mapped[int] = mapped_column(Integer, default=6)  # complete months the typical month comes from
    monthly_override: Mapped[int | None] = mapped_column(Integer)  # paise; replaces the calculated amount
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ...db import Base


class BillRepeat(enum.StrEnum):
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    half_yearly = "half_yearly"
    yearly = "yearly"


class Bill(Base):
    __tablename__ = "bill"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    amount_min: Mapped[int] = mapped_column(Integer)  # paise
    amount_max: Mapped[int] = mapped_column(Integer)  # paise
    first_due: Mapped[date] = mapped_column(Date)  # anchor for the schedule
    repeat: Mapped[str] = mapped_column(String(16), default=BillRepeat.monthly)
    skip: Mapped[int] = mapped_column(Integer, default=0)  # 1 = every other period
    # Comma-separated words; a new expense matches when one appears in its
    # description or payee AND the amount is within [min, max].
    match: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

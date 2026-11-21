import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ...db import Base


class BudgetMode(enum.StrEnum):
    manual = "manual"  # you set each month's amount yourself
    fixed = "fixed"  # the same amount every month
    rollover = "rollover"  # amount + whatever was left (or overspent) last month, never below 0


class Budget(Base):
    __tablename__ = "budget"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    mode: Mapped[str] = mapped_column(String(16), default=BudgetMode.manual)
    amount: Mapped[int] = mapped_column(Integer, default=0)  # paise per month (fixed / rollover)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BudgetCategory(Base):
    """A category a budget counts by itself: its expenses go to this budget unless you put
    them in another one by hand. A category belongs to at most one budget."""

    __tablename__ = "budget_category"
    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budget.id", ondelete="CASCADE", name="fk_budget_category_budget_id_budget"), index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("category.id", ondelete="CASCADE", name="fk_budget_category_category_id_category"), unique=True
    )


class BudgetLimit(Base):
    """The amount available in one budget for one month."""

    __tablename__ = "budget_limit"
    __table_args__ = (UniqueConstraint("budget_id", "month", name="uq_budget_limit_budget_id_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(
        ForeignKey("budget.id", ondelete="CASCADE", name="fk_budget_limit_budget_id_budget"), index=True
    )
    month: Mapped[date] = mapped_column(Date)  # first day of the month
    amount: Mapped[int] = mapped_column(Integer)
    # True when filled in from the budget's mode; amounts you set by hand are never overwritten.
    auto_generated: Mapped[bool] = mapped_column(Boolean, default=False)

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...db import Base
from ..accounts.models import Account


class PiggyBank(Base):
    """A savings goal. The money stays in the linked bank or cash account; the
    piggy bank only earmarks part of that balance."""

    __tablename__ = "piggy_bank"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    account_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE", name="fk_piggy_bank_account_id_account"), index=True
    )
    target_amount: Mapped[int] = mapped_column(Integer)  # paise
    target_date: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    account: Mapped[Account] = relationship(lazy="joined")


class PiggyEvent(Base):
    """Money set aside (+) or taken out (−) of a piggy bank."""

    __tablename__ = "piggy_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    piggy_id: Mapped[int] = mapped_column(
        ForeignKey("piggy_bank.id", ondelete="CASCADE", name="fk_piggy_event_piggy_id_piggy_bank"), index=True
    )
    date: Mapped[date] = mapped_column(Date)
    amount: Mapped[int] = mapped_column(Integer)  # paise, + set aside, − taken out
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

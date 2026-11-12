import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ...db import Base


class AccountType(enum.StrEnum):
    asset = "asset"  # bank accounts, wallets you own
    cash = "cash"  # physical cash
    expense = "expense"  # where money goes (merchants, payees)
    revenue = "revenue"  # where money comes from (employer, refunds)


# Accounts that hold a balance you own. Expense/revenue accounts are
# counterparties: they only accumulate totals. (Credit cards and loans come
# later as their own features.)
BALANCE_TYPES = {AccountType.asset, AccountType.cash}


class Account(Base):
    __tablename__ = "account"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(16), index=True)
    account_number: Mapped[str | None] = mapped_column(String(64))
    opening_balance: Mapped[int] = mapped_column(Integer, default=0)  # paise; may be negative (overdrawn)
    opening_date: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

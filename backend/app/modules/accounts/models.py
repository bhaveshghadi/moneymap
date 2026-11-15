import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ...db import Base


class AccountType(enum.StrEnum):
    asset = "asset"  # bank accounts, wallets you own
    cash = "cash"  # physical cash
    credit_card = "credit_card"  # balance below zero = owed on the card (details in modules/cards)
    emi_plan = "emi_plan"  # a card EMI: balance below zero = principal still to pay (modules/cards/emi.py)
    loan = "loan"  # a loan (modules/loans); what is left comes from its schedule
    expense = "expense"  # where money goes (merchants, payees)
    revenue = "revenue"  # where money comes from (employer, refunds)


# Accounts that hold a balance you own. Expense/revenue accounts are
# counterparties: they only accumulate totals. (Loans come later.)
BALANCE_TYPES = {AccountType.asset, AccountType.cash}
# Your own accounts that transactions can use: bank, cash and credit cards. Spending on a
# card is an expense from the card; paying the bill is a transfer bank -> card.
OWN_TYPES = BALANCE_TYPES | {AccountType.credit_card, AccountType.emi_plan, AccountType.loan}
# Made and changed on the Credit cards page only.
CARD_TYPES = {AccountType.credit_card, AccountType.emi_plan, AccountType.loan}  # + loans (Loans page)


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

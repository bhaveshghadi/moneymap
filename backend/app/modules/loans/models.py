"""Loans: terms on top of an account of type `loan`.

How a loan counts as spending is chosen per loan (`count_mode`):
- whole_emi: each EMI is ONE expense (category "Loan / EMI"); what's left is worked
  out from the schedule and the EMIs actually paid. For loans whose money you don't
  record being spent (home / car loan paid to the seller, consumer loans, old loans).
- interest_only: each EMI is a transfer bank -> loan (principal, paying back) plus an
  expense (category "Loan Interest"). For loans whose money came into your bank and
  whose spending you record yourself.
Either way the loan money arriving in your bank is a transfer loan -> bank, not income.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...db import Base
from ..accounts.models import Account

LOAN_KINDS = ("home", "car", "two_wheeler", "personal", "education", "gold", "property", "consumer", "other")


class Loan(Base):
    __tablename__ = "loan"
    __table_args__ = (UniqueConstraint("account_id", name="uq_loan_account_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", name="fk_loan_account_id_account", ondelete="CASCADE")
    )
    lender: Mapped[str | None] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16), default="personal")  # LOAN_KINDS
    loan_number: Mapped[str | None] = mapped_column(String(32))  # (last digits) for matching bank rows
    method: Mapped[str] = mapped_column(String(12), default="reducing")  # reducing | flat | emi_only
    count_mode: Mapped[str] = mapped_column(String(16), default="whole_emi")  # whole_emi | interest_only
    principal: Mapped[int | None] = mapped_column(Integer)  # paise borrowed (optional for emi_only)
    rate_bp: Mapped[int | None] = mapped_column(Integer)  # yearly %, x100
    tenure: Mapped[int] = mapped_column(Integer)  # number of EMIs
    emi: Mapped[int] = mapped_column(Integer)  # paise, as the lender charges it
    first_emi_date: Mapped[date] = mapped_column(Date)
    disbursed_date: Mapped[date | None] = mapped_column(Date)
    # EMI 1's interest: one month (month) or the days from disbursed_date, on a 365 / 360-day year
    first_interest: Mapped[str] = mapped_column(String(8), default="month", server_default="month")
    pay_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("account.id", name="fk_loan_pay_from_id_account", ondelete="SET NULL")
    )  # the bank account the EMI is paid from
    paid_before: Mapped[int] = mapped_column(Integer, default=0)  # EMIs paid before tracking started
    closed_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    account: Mapped[Account] = relationship(foreign_keys=[account_id], lazy="joined")
    pay_from: Mapped[Account | None] = relationship(foreign_keys=[pay_from_id], lazy="joined")
    events: Mapped[list["LoanEvent"]] = relationship(
        order_by="LoanEvent.date", cascade="all, delete-orphan", lazy="selectin"
    )


class LoanEvent(Base):
    """A part-payment or an interest-rate change on a reducing-balance loan. The
    schedule applies it before the first EMI dated after it (loans/maths.build_events)."""

    __tablename__ = "loan_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(
        ForeignKey("loan.id", name="fk_loan_event_loan_id_loan", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(8))  # prepay | rate
    date: Mapped[date] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(16))  # reduce_tenure (EMI stays) | reduce_emi (end date stays)
    amount: Mapped[int | None] = mapped_column(Integer)  # prepay: paise
    rate_bp: Mapped[int | None] = mapped_column(Integer)  # rate: the new yearly rate x100
    txn_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction.id", name="fk_loan_event_txn_id_transaction", ondelete="SET NULL")
    )  # prepay: the payment
    txn_created: Mapped[bool] = mapped_column(Boolean, default=False)  # made here (deleted with the event)
    fee_txn_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction.id", name="fk_loan_event_fee_txn_id_transaction", ondelete="SET NULL")
    )  # prepay: the lender's charge, if any
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

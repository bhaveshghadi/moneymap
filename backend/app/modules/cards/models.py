"""Credit cards: card details on top of a `credit_card` account, and the billing-cycle
rules over time (a new rule applies from the next cycle, so past cycles keep their dates)."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...db import Base
from ..accounts.models import Account


class CreditCard(Base):
    __tablename__ = "credit_card"
    __table_args__ = (UniqueConstraint("account_id", name="uq_credit_card_account_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", name="fk_credit_card_account_id_account", ondelete="CASCADE")
    )
    bank: Mapped[str | None] = mapped_column(String(80))
    last4: Mapped[str | None] = mapped_column(String(4))
    network: Mapped[str | None] = mapped_column(String(24))  # visa, mastercard, rupay, amex, diners
    credit_limit: Mapped[int] = mapped_column(Integer, default=0)  # paise; 0 = not set
    min_due_pct: Mapped[int] = mapped_column(Integer, default=5)  # % of the statement total
    color: Mapped[str] = mapped_column(String(16), default="indigo")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    account: Mapped[Account] = relationship(lazy="joined")
    rules: Mapped[list["CardCycleRule"]] = relationship(
        order_by="CardCycleRule.effective_from", cascade="all, delete-orphan", lazy="selectin"
    )


class CardCycleRule(Base):
    """Statement day and due date rule, in force for statements dated on/after `effective_from`."""

    __tablename__ = "card_cycle_rule"
    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("credit_card.id", name="fk_card_cycle_rule_card_id_credit_card", ondelete="CASCADE"), index=True
    )
    effective_from: Mapped[date] = mapped_column(Date)
    statement_day: Mapped[int] = mapped_column(Integer)  # 1-31; 31 = last day of shorter months
    due_mode: Mapped[str] = mapped_column(String(16))  # days_after | fixed_day
    due_value: Mapped[int] = mapped_column(Integer)  # days after the statement, or day of month


class CardEmi(Base):
    """An EMI on a card: a purchase paid back in monthly instalments. It has its own
    account (type emi_plan) holding the principal still to pay:
    - converted purchase: the "converted to EMI" credit is a transfer plan -> card
    - EMI at checkout: the purchase is an expense from the plan (full amount, once)
    - each month's principal is a transfer card -> plan (it lands on the card bill)
    - interest, GST and fees are expenses from the card, linked by transaction.emi_id."""

    __tablename__ = "card_emi"
    __table_args__ = (UniqueConstraint("account_id", name="uq_card_emi_account_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("credit_card.id", name="fk_card_emi_card_id_credit_card", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", name="fk_card_emi_account_id_account", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))  # merchant / what was bought
    kind: Mapped[str] = mapped_column(String(12))  # converted | checkout | existing
    principal: Mapped[int] = mapped_column(Integer)  # paise
    tenure: Mapped[int] = mapped_column(Integer)  # number of monthly instalments
    instalment: Mapped[int | None] = mapped_column(Integer)  # monthly amount incl. interest, if known
    interest_rate_bp: Mapped[int | None] = mapped_column(Integer)  # yearly %, x100 (15.99% = 1599)
    processing_fee: Mapped[int | None] = mapped_column(Integer)
    no_cost: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[date] = mapped_column(Date)  # first instalment
    paid_before: Mapped[int] = mapped_column(Integer, default=0)  # instalments paid before tracking (existing)
    created_txn_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction.id", name="fk_card_emi_created_txn_id_transaction", ondelete="SET NULL")
    )  # the conversion transfer / checkout purchase made with the plan
    purchase_txn_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction.id", name="fk_card_emi_purchase_txn_id_transaction", ondelete="SET NULL")
    )  # converted: the original card purchase
    closed_on: Mapped[date | None] = mapped_column(Date)  # closed early
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    account: Mapped[Account] = relationship(lazy="joined")

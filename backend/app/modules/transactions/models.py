import enum
from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Table, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...db import Base
from ..accounts.models import Account
from ..bills.models import Bill
from ..budgets.models import Budget
from ..categories.models import Category, Tag


class TransactionType(enum.StrEnum):
    withdrawal = "withdrawal"  # expense: balance account -> expense account
    deposit = "deposit"  # income: revenue account -> balance account
    transfer = "transfer"  # balance account -> balance account


transaction_tag = Table(
    "transaction_tag",
    Base.metadata,
    Column(
        "transaction_id",
        ForeignKey("transaction.id", ondelete="CASCADE", name="fk_transaction_tag_transaction_id_transaction"),
        primary_key=True,
    ),
    Column("tag_id", ForeignKey("tag.id", ondelete="CASCADE", name="fk_transaction_tag_tag_id_tag"), primary_key=True),
)


class Transaction(Base):
    """Money moves from `source` to `destination`; the amount is always positive paise."""

    __tablename__ = "transaction"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(16), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(255))
    source_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", name="fk_transaction_source_id_account"), index=True
    )
    destination_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", name="fk_transaction_destination_id_account"), index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id", ondelete="SET NULL", name="fk_transaction_category_id_category"), index=True
    )
    # Only expenses carry a budget (F6).
    budget_id: Mapped[int | None] = mapped_column(
        ForeignKey("budget.id", ondelete="SET NULL", name="fk_transaction_budget_id_budget"), index=True
    )
    # Only expenses are linked to a bill (F7).
    bill_id: Mapped[int | None] = mapped_column(
        ForeignKey("bill.id", ondelete="SET NULL", name="fk_transaction_bill_id_bill"), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    source: Mapped[Account] = relationship(foreign_keys=[source_id], lazy="joined")
    destination: Mapped[Account] = relationship(foreign_keys=[destination_id], lazy="joined")
    category: Mapped[Category | None] = relationship(lazy="joined")
    budget: Mapped[Budget | None] = relationship(lazy="joined")
    bill: Mapped[Bill | None] = relationship(lazy="joined")
    tags: Mapped[list[Tag]] = relationship(secondary=transaction_tag, lazy="selectin")

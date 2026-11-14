from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...db import Base


class StatementImport(Base):
    """A statement PDF (from the Inbox or uploaded) being reviewed / imported."""

    __tablename__ = "statement_import"
    id: Mapped[int] = mapped_column(primary_key=True)
    gmail_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("gmail_message.id", ondelete="SET NULL", name="fk_statement_import_gmail_message_id_gmail_message")
    )
    attachment_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "gmail_attachment.id", ondelete="SET NULL", name="fk_statement_import_attachment_id_gmail_attachment"
        )
    )
    upload_path: Mapped[str | None] = mapped_column(String(255))  # uploaded PDF, relative to <data_dir>/uploads
    file_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    doc_type: Mapped[str] = mapped_column(String(32))  # bank_statement | card_statement
    account_last4: Mapped[str | None] = mapped_column(String(8))
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("account.id", ondelete="SET NULL", name="fk_statement_import_account_id_account")
    )
    text: Mapped[str] = mapped_column(Text)  # extracted text, kept so the password isn't needed again
    unparsed: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | imported
    # Card statements: the summary box (each figure optional; see card_summary.py)
    statement_date: Mapped[date | None] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    total_due: Mapped[int | None] = mapped_column(Integer)
    min_due: Mapped[int | None] = mapped_column(Integer)
    previous_balance: Mapped[int | None] = mapped_column(Integer)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    imported_at: Mapped[datetime | None] = mapped_column(DateTime)

    rows: Mapped[list["StatementRow"]] = relationship(
        back_populates="statement", cascade="all, delete-orphan", order_by="StatementRow.idx", lazy="selectin"
    )


class StatementRow(Base):
    __tablename__ = "statement_row"
    id: Mapped[int] = mapped_column(primary_key=True)
    import_id: Mapped[int] = mapped_column(
        ForeignKey("statement_import.id", ondelete="CASCADE", name="fk_statement_row_import_id_statement_import"),
        index=True,
    )
    idx: Mapped[int] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date)
    amount: Mapped[int] = mapped_column(Integer)  # signed paise: − money out of the account, + money in
    description: Mapped[str] = mapped_column(String(255))
    raw: Mapped[str] = mapped_column(Text)  # the original statement line(s)
    counterparty: Mapped[str | None] = mapped_column(String(120))
    name_hint: Mapped[str | None] = mapped_column(String(120))  # payee line printed above the row
    balance: Mapped[int | None] = mapped_column(Integer)
    # review
    include: Mapped[bool] = mapped_column(Boolean, default=True)
    kind: Mapped[str] = mapped_column(String(16))  # expense | income | transfer
    payee: Mapped[str] = mapped_column(String(120))
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id", ondelete="SET NULL", name="fk_statement_row_category_id_category")
    )
    budget_id: Mapped[int | None] = mapped_column(
        ForeignKey("budget.id", ondelete="SET NULL", name="fk_statement_row_budget_id_budget")
    )
    transfer_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("account.id", ondelete="SET NULL", name="fk_statement_row_transfer_account_id_account")
    )
    leave_uncategorised: Mapped[bool] = mapped_column(Boolean, default=False)
    user_set: Mapped[bool] = mapped_column(Boolean, default=False)  # you changed it; suggestions won't overwrite
    suggestion: Mapped[str | None] = mapped_column(String(160))  # why the category was filled in
    suggestion_kind: Mapped[str | None] = mapped_column(String(16))  # history
    duplicate_of: Mapped[int | None] = mapped_column(
        ForeignKey("transaction.id", ondelete="SET NULL", name="fk_statement_row_duplicate_of_transaction")
    )
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction.id", ondelete="SET NULL", name="fk_statement_row_transaction_id_transaction")
    )
    # Card bill payment already recorded on the bank side as an expense: importing turns
    # that expense into the bank -> card transfer instead of adding a second entry.
    link_txn_id: Mapped[int | None] = mapped_column(
        ForeignKey("transaction.id", ondelete="SET NULL", name="fk_statement_row_link_txn_id_transaction")
    )
    flag: Mapped[str | None] = mapped_column(String(16))  # emi: an EMI row with no plan to match yet
    emi_id: Mapped[int | None] = mapped_column(
        ForeignKey("card_emi.id", ondelete="SET NULL", name="fk_statement_row_emi_id_card_emi")
    )  # the card EMI this row belongs to (instalment, interest, GST, conversion)

    statement: Mapped[StatementImport] = relationship(back_populates="rows")

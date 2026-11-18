from datetime import date as Date
from datetime import datetime

from pydantic import BaseModel, Field

from ...core.schemas import ORM
from ..transactions.schemas import TransactionOut


class StatementStartIn(BaseModel):
    attachment_id: int
    password: str | None = Field(default=None, max_length=200)
    remember_password: bool = False


class StatementUploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_b64: str = Field(min_length=1)  # the PDF, base64-encoded
    account_id: int | None = None  # empty = pick it from the account number on the statement
    password: str | None = Field(default=None, max_length=200)
    remember_password: bool = False  # remembered for the chosen account
    cas: bool = False  # uploaded from Investments -> Import CAS (the password is remembered for CAS PDFs)


class StatementRereadIn(BaseModel):
    password: str | None = Field(default=None, max_length=200)
    remember_password: bool = False


class StatementRowOut(ORM):
    id: int
    idx: int
    date: Date
    amount: int
    description: str
    raw: str
    counterparty: str | None
    name_hint: str | None = None
    balance: int | None
    include: bool
    kind: str
    payee: str
    category_id: int | None
    budget_id: int | None
    transfer_account_id: int | None
    leave_uncategorised: bool
    user_set: bool
    suggestion: str | None
    suggestion_kind: str | None
    duplicate_of: int | None
    duplicate: TransactionOut | None = None
    link_txn_id: int | None = None  # bank-side expense this payment row will turn into the transfer
    link: TransactionOut | None = None
    flag: str | None = None  # emi: an EMI row with no plan to match yet
    emi_id: int | None = None  # the card EMI it belongs to
    loan_id: int | None = None  # bank statement: a loan's EMI or part-payment (recorded on import)
    loan_action: str | None = None  # emi | prepay
    transaction_id: int | None
    status: str = ""


class StatementSummary(ORM):
    id: int
    filename: str
    doc_type: str
    account_last4: str | None
    account_id: int | None
    gmail_message_id: str | None
    upload_path: str | None = None
    status: str
    imported_count: int
    created_at: datetime
    imported_at: datetime | None
    row_count: int = 0
    counts: dict[str, int] = {}


class StatementOverlap(BaseModel):
    """Another statement import with the same transactions (e.g. the same
    statement, once from Gmail and once uploaded)."""

    id: int
    filename: str
    source: str  # email | upload
    status: str  # draft | imported
    shared_rows: int


class CardFigures(BaseModel):
    """A card statement's summary box (each figure only if found) and the add-up check:
    previous balance + purchases - credits should equal the total due."""

    statement_date: Date | None = None
    period_start: Date | None = None
    due_date: Date | None = None
    total_due: int | None = None
    min_due: int | None = None
    previous_balance: int | None = None
    debits: int = 0  # all rows of the statement
    credits: int = 0
    expected_total: int | None = None
    difference: int | None = None  # total_due - expected_total
    adds_up: bool | None = None  # None = not enough figures to check
    # the card's billing cycle vs this statement: a different statement day / due gap is suggested
    card_statement_day: int | None = None
    card_due_mode: str | None = None
    card_due_value: int | None = None
    suggest_statement_day: int | None = None
    suggest_due_days: int | None = None


class StatementDetail(StatementSummary):
    unparsed: list[str]
    rows: list[StatementRowOut]
    account_suggested: bool = False  # account picked automatically from the statement's last 4 digits
    overlaps: list[StatementOverlap] = []
    figures: CardFigures | None = None  # card statements only
    # upload only: this exact file was already opened (from the Inbox or an
    # earlier upload), so that statement is returned instead of a new draft
    opened_existing: bool = False


class StatementPatch(BaseModel):
    account_id: int | None = None


class StatementRowPatch(BaseModel):
    include: bool | None = None
    kind: str | None = Field(default=None, pattern="^(expense|income|transfer)$")
    payee: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=255)
    date: Date | None = None
    amount: int | None = None
    category_id: int | None = None
    budget_id: int | None = None
    transfer_account_id: int | None = None
    leave_uncategorised: bool | None = None
    link_txn_id: int | None = None  # only null: import the payment row as a new transfer instead
    loan_id: int | None = None  # only null: import it as a plain expense, not as the loan's EMI / part-payment


class StatementImportOut(BaseModel):
    imported: int
    statement: StatementDetail

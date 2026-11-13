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


class StatementDetail(StatementSummary):
    unparsed: list[str]
    rows: list[StatementRowOut]
    account_suggested: bool = False  # account picked automatically from the statement's last 4 digits
    overlaps: list[StatementOverlap] = []
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


class StatementImportOut(BaseModel):
    imported: int
    statement: StatementDetail

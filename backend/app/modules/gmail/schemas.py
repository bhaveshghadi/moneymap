from datetime import date as Date
from datetime import datetime

from pydantic import BaseModel, Field

from ...core.schemas import ORM
from ..transactions.schemas import TransactionOut


class GmailClientIn(BaseModel):
    json_text: str = Field(min_length=2, max_length=20_000)


class GmailConnectIn(BaseModel):
    origin: str = Field(max_length=255)  # the browser's origin, for the loopback redirect


class GmailPasteIn(BaseModel):
    url: str = Field(max_length=4000)


class GmailConnectOut(BaseModel):
    url: str  # Google's consent page
    redirect_uri: str
    direct: bool  # False: the browser isn't on the server's machine — paste the URL back


class GmailStatus(BaseModel):
    client_configured: bool
    client_from_env: bool = False  # set in MONEYMAP_GOOGLE_CLIENT_JSON: not pasted or removed in Settings
    client_env_error: str | None = None  # set but unreadable
    client_id_hint: str | None = None
    connected: bool
    email: str | None = None
    connected_at: str | None = None
    last_fetch_to: Date | None = None
    consent_threshold_mb: int


class GmailProvider(BaseModel):
    id: str
    provider_id: str
    name: str
    doc_type: str  # readable kind
    kind: str  # bank_statement | credit_card_statement | loan_statement | mf_statement | transaction_alert


class GmailEstimateIn(BaseModel):
    template_ids: list[str] = []
    custom: list[str] = []
    date_from: Date
    date_to: Date


class GmailRunOut(ORM):
    id: int
    status: str
    date_from: Date
    date_to: Date
    queries: list[dict]
    matched_count: int
    new_count: int
    bytes_estimated: int
    bytes_human: str = ""
    consent_required: bool = False
    message_count: int
    attachment_count: int
    bytes_downloaded: int
    progress: str | None
    error: str | None


class GmailStartIn(BaseModel):
    consent: bool = False


class AttachmentOut(ORM):
    id: int
    filename: str
    mime_type: str | None
    size: int


class InboxItem(ORM):
    id: str
    from_addr: str | None
    subject: str | None
    sent_at: datetime | None
    snippet: str | None
    provider_id: str | None
    doc_type: str | None
    status: str
    attachments: list[AttachmentOut]
    transaction_count: int = 0
    is_alert: bool = False  # recognised as a transaction alert (a suggestion is ready)


class AlertSuggestionOut(BaseModel):
    """Pre-fill for the transaction form, read from a transaction alert email."""

    type: str  # withdrawal | deposit
    amount: int
    date: Date
    merchant: str | None
    account_last4: str | None
    account_id: int | None  # your bank/cash account whose number ends with account_last4
    category_id: int | None = None  # from your rules
    payee: str | None = None  # the merchant, renamed by a rule
    rule: str | None = None  # the rule(s) that matched


class InboxDetail(InboxItem):
    body_text: str | None
    matched_query: str | None
    transactions: list[TransactionOut] = []
    suggestion: AlertSuggestionOut | None = None


class InboxPage(BaseModel):
    items: list[InboxItem]
    total: int
    counts: dict[str, int]


class InboxStatusIn(BaseModel):
    status: str = Field(pattern="^(new|ignored)$")

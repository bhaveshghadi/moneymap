import json
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...core.crypto import DecryptError, decrypt, encrypt
from ...db import Base


class GmailAccount(Base):
    """The user's own Google OAuth client and its token (at most one row, id=1).
    The client secret and the token are stored encrypted."""

    __tablename__ = "gmail_account"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(255))
    client_secret_enc: Mapped[str] = mapped_column(Text)
    token_enc: Mapped[str | None] = mapped_column(Text)  # encrypted JSON: access/refresh token, expiry
    email: Mapped[str | None] = mapped_column(String(320))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_fetch_to: Mapped[date | None] = mapped_column(Date)  # default start for the next fetch

    @property
    def client_secret(self) -> str:
        return decrypt(self.client_secret_enc)

    @client_secret.setter
    def client_secret(self, value: str) -> None:
        self.client_secret_enc = encrypt(value)

    @property
    def token(self) -> dict | None:
        if not self.token_enc:
            return None
        try:
            return json.loads(decrypt(self.token_enc))
        except DecryptError:
            return None  # treated as not connected; the user reconnects

    @token.setter
    def token(self, value: dict | None) -> None:
        self.token_enc = encrypt(json.dumps(value)) if value else None


class GmailRun(Base):
    """One estimate + fetch."""

    __tablename__ = "gmail_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(
        String(16), default="estimated"
    )  # estimated|running|cancelling|done|cancelled|error
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    queries: Mapped[list] = mapped_column(JSON, default=list)  # [{label, provider_id, doc_type, query}]
    pending_ids: Mapped[list] = mapped_column(JSON, default=list)  # [[message_id, query_index], ...] not yet stored
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    bytes_estimated: Mapped[int] = mapped_column(Integer, default=0)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    attachment_count: Mapped[int] = mapped_column(Integer, default=0)
    bytes_downloaded: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class GmailMessage(Base):
    __tablename__ = "gmail_message"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # Gmail message id
    thread_id: Mapped[str | None] = mapped_column(String(64))
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("gmail_run.id", ondelete="SET NULL", name="fk_gmail_message_run_id_gmail_run")
    )
    from_addr: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    snippet: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    provider_id: Mapped[str | None] = mapped_column(String(80))
    doc_type: Mapped[str | None] = mapped_column(
        String(32)
    )  # bank_statement | credit_card_statement | transaction_alert …
    matched_query: Mapped[str | None] = mapped_column(Text)
    size_estimate: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)  # new | handled | ignored
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    attachments: Mapped[list["GmailAttachment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", lazy="selectin", order_by="GmailAttachment.id"
    )


class GmailAttachment(Base):
    __tablename__ = "gmail_attachment"
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("gmail_message.id", ondelete="CASCADE", name="fk_gmail_attachment_message_id_gmail_message"),
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str] = mapped_column(String(500))  # relative to <data_dir>/gmail

    message: Mapped[GmailMessage] = relationship(back_populates="attachments")

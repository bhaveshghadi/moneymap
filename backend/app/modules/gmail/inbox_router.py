from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...db import get_db
from ..accounts.models import BALANCE_TYPES, Account
from ..auth.security import current_user
from ..transactions.models import Transaction
from ..transactions.service import txn_out
from .alerts import parse_alert
from .fetch import attachments_dir
from .models import GmailAttachment, GmailMessage
from .schemas import AlertSuggestionOut, InboxDetail, InboxItem, InboxPage, InboxStatusIn

router = APIRouter(prefix="/inbox", tags=["inbox"], dependencies=[Depends(current_user)])

# Types that are safe to show inline in the browser; everything else downloads.
INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/gif", "text/plain"}


def _counts(db: Session) -> dict[str, int]:
    base = {"new": 0, "handled": 0, "ignored": 0}
    base.update(dict(db.execute(select(GmailMessage.status, func.count()).group_by(GmailMessage.status)).all()))
    return base


def _linked(db: Session, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    return dict(
        db.execute(
            select(Transaction.gmail_message_id, func.count())
            .where(Transaction.gmail_message_id.in_(ids))
            .group_by(Transaction.gmail_message_id)
        ).all()
    )


def suggestion_for(db: Session, m: GmailMessage) -> AlertSuggestionOut | None:
    """Transaction pre-fill for an alert email; None for statements and other emails."""
    if m.attachments and m.doc_type != "transaction_alert":
        return None  # statements come with a PDF — that's for statement import
    s = parse_alert(m.subject, m.body_text or m.snippet, m.sent_at)
    if s is None:
        return None
    account_id = None
    if s.account_last4:
        matches = [
            a.id
            for a in db.scalars(
                select(Account).where(Account.type.in_([str(t) for t in BALANCE_TYPES]), Account.active.is_(True))
            )
            if (a.account_number or "").replace(" ", "").endswith(s.account_last4)
        ]
        account_id = matches[0] if len(matches) == 1 else None
    return AlertSuggestionOut(
        type=s.type,
        amount=s.amount,
        date=s.date,
        merchant=s.merchant,
        account_last4=s.account_last4,
        account_id=account_id,
    )


@router.get("/counts")
def counts(db: Session = Depends(get_db)) -> dict[str, int]:
    return _counts(db)


@router.get("", response_model=InboxPage)
def list_inbox(
    status_: str = Query(default="new", alias="status", pattern="^(new|handled|ignored|all)$"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> InboxPage:
    """Fetched emails, newest first (default: the ones still to deal with)."""
    query = select(GmailMessage)
    if status_ != "all":
        query = query.where(GmailMessage.status == status_)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(
            or_(GmailMessage.subject.ilike(like), GmailMessage.from_addr.ilike(like), GmailMessage.snippet.ilike(like))
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(db.scalars(query.order_by(GmailMessage.sent_at.desc()).limit(limit).offset(offset)))
    linked = _linked(db, [m.id for m in rows])
    items = []
    for m in rows:
        item = InboxItem.model_validate(m)
        item.transaction_count = linked.get(m.id, 0)
        item.is_alert = suggestion_for(db, m) is not None
        items.append(item)
    return InboxPage(items=items, total=total, counts=_counts(db))


def _get(db: Session, mid: str) -> GmailMessage:
    m = db.get(GmailMessage, mid)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email not found")
    return m


def _detail(db: Session, m: GmailMessage) -> InboxDetail:
    out = InboxDetail.model_validate(m)
    txns = list(
        db.scalars(select(Transaction).where(Transaction.gmail_message_id == m.id).order_by(Transaction.date)).unique()
    )
    out.transactions = [txn_out(t) for t in txns]
    out.transaction_count = len(txns)
    out.suggestion = suggestion_for(db, m)
    out.is_alert = out.suggestion is not None
    return out


@router.get("/{mid}", response_model=InboxDetail)
def get_message(mid: str, db: Session = Depends(get_db)) -> InboxDetail:
    """One email with its body, attachments, linked transactions and (for alerts) a suggestion."""
    return _detail(db, _get(db, mid))


@router.patch("/{mid}", response_model=InboxDetail)
def set_status(mid: str, body: InboxStatusIn, db: Session = Depends(get_db)) -> InboxDetail:
    """Ignore an email, or restore it (it becomes 'handled' again if transactions link to it)."""
    m = _get(db, mid)
    if body.status == "ignored":
        m.status = "ignored"
    else:
        linked = db.scalar(select(func.count(Transaction.id)).where(Transaction.gmail_message_id == m.id))
        m.status = "handled" if linked else "new"
    db.commit()
    return _detail(db, m)


@router.get("/{mid}/attachments/{aid}")
def get_attachment(mid: str, aid: int, download: bool = False, db: Session = Depends(get_db)) -> FileResponse:
    att = db.get(GmailAttachment, aid)
    if att is None or att.message_id != mid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    folder = attachments_dir().resolve()
    path = (folder / att.path).resolve()
    if folder not in path.parents or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment file is missing")
    mime = att.mime_type or "application/octet-stream"
    inline = not download and mime in INLINE_TYPES
    headers = {"X-Content-Type-Options": "nosniff"}
    # Chrome won't run its PDF viewer on a sandboxed page, so PDFs skip the sandbox; everything else keeps it.
    if mime != "application/pdf":
        headers["Content-Security-Policy"] = "sandbox"
    return FileResponse(
        path,
        media_type=mime,
        filename=att.filename,
        content_disposition_type="inline" if inline else "attachment",
        headers=headers,
    )

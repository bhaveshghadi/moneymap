import base64
import binascii
import hashlib
import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.crypto import DecryptError, decrypt, encrypt
from ...core.once import one_at_a_time
from ...db import get_db, user_dir
from ..accounts.models import OWN_TYPES, Account, AccountType
from ..auth.models import Setting
from ..auth.security import current_user
from ..budgets.models import Budget
from ..cards.models import CreditCard
from ..categories.models import Category
from ..gmail.fetch import attachments_dir
from ..gmail.models import GmailAttachment
from ..loans.actions import link_payments, record_prepay
from ..loans.models import Loan
from ..loans.statement import is_loan_statement
from ..transactions.models import Transaction, TransactionType
from ..transactions.schemas import TransactionIn
from ..transactions.service import apply_body, sync_inbox_status, txn_out
from .card_summary import parse_card_summary
from .extract import StatementError, extract_candidates
from .models import StatementImport, StatementRow
from .parser import parse_statement, score
from .review import payee_from, payee_key, refresh, row_status
from .schemas import (
    CardFigures,
    StatementDetail,
    StatementImportOut,
    StatementOverlap,
    StatementPatch,
    StatementRereadIn,
    StatementRowOut,
    StatementRowPatch,
    StatementStartIn,
    StatementSummary,
    StatementUploadIn,
)

log = logging.getLogger("moneymap.statements")
router = APIRouter(prefix="/statements", tags=["statement import"], dependencies=[Depends(current_user)])

# bank, cash and credit cards (not investments)
BALANCE_TYPES = tuple(str(t) for t in OWN_TYPES if t != AccountType.investment)
ROUNDING = 100  # paise: a statement "adds up" within ₹1
CAS_PASSWORD_KEY = "pdf_password:cas"  # a CAS uploaded from Investments
CAS_RE = re.compile(r"consolidated\s+account\s+(?:statement|summary)", re.I)  # detailed or summary


def is_cas(text: str) -> bool:
    """A mutual fund Consolidated Account Statement (imported in Investments)."""
    return bool(CAS_RE.search(text[:3000])) and bool(re.search(r"folio", text, re.I))


def _bad(msg: str, code: str = "invalid") -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": code, "message": msg})


def _counts(rows: list[StatementRow]) -> dict[str, int]:
    out = {"ready": 0, "link": 0, "needs_category": 0, "needs_account": 0, "duplicate": 0, "skipped": 0, "imported": 0}
    for r in rows:
        out[row_status(r)] += 1
    return out


def _summary(imp: StatementImport) -> StatementSummary:
    s = StatementSummary.model_validate(imp)
    s.row_count = len(imp.rows)
    s.counts = _counts(imp.rows)
    return s


def _figures(db: Session, imp: StatementImport) -> CardFigures | None:
    """A card statement's summary box, and whether its rows add up to the total due."""
    account = db.get(Account, imp.account_id) if imp.account_id else None
    is_card = imp.doc_type == "card_statement" or (account is not None and account.type == AccountType.credit_card)
    if not is_card:
        return None
    debits = sum(-r.amount for r in imp.rows if r.amount < 0)
    credits = sum(r.amount for r in imp.rows if r.amount > 0)
    f = CardFigures(
        statement_date=imp.statement_date,
        period_start=imp.period_start,
        due_date=imp.due_date,
        total_due=imp.total_due,
        min_due=imp.min_due,
        previous_balance=imp.previous_balance,
        debits=debits,
        credits=credits,
    )
    if account is not None and account.type == AccountType.credit_card and imp.statement_date:
        card = db.scalar(select(CreditCard).where(CreditCard.account_id == account.id))
        if card is not None and card.rules:
            rule = card.rules[-1]
            sd = imp.statement_date
            month_end = (sd + timedelta(days=1)).day == 1
            if sd.day != rule.statement_day and not (month_end and rule.statement_day >= sd.day):
                f.suggest_statement_day = sd.day
            if imp.due_date and rule.due_mode == "days_after" and (imp.due_date - sd).days != rule.due_value:
                gap = (imp.due_date - sd).days
                if 1 <= gap <= 60:
                    f.suggest_due_days = gap
            f.card_statement_day, f.card_due_mode, f.card_due_value = rule.statement_day, rule.due_mode, rule.due_value
    if imp.total_due is not None and imp.previous_balance is not None:
        f.expected_total = imp.previous_balance + debits - credits
        f.difference = imp.total_due - f.expected_total
        f.adds_up = abs(f.difference) <= ROUNDING
    return f


def _apply_summary(imp: StatementImport) -> None:
    """Read the card summary box from the statement text (card statements only)."""
    if imp.doc_type != "card_statement":
        return
    s = parse_card_summary(imp.text)
    imp.statement_date, imp.period_start, imp.due_date = s.statement_date, s.period_start, s.due_date
    imp.total_due, imp.min_due, imp.previous_balance = s.total_due, s.min_due, s.previous_balance


def _detail(db: Session, imp: StatementImport, account_suggested: bool | None = None) -> StatementDetail:
    if account_suggested is None:
        auto = _match_account(db, imp.account_last4, imp.doc_type)
        account_suggested = auto is not None and auto.id == imp.account_id
    rows = []
    for r in imp.rows:
        out = StatementRowOut.model_validate(r)
        out.status = row_status(r)
        if r.duplicate_of:
            t = db.get(Transaction, r.duplicate_of)
            out.duplicate = txn_out(t) if t else None
        if r.link_txn_id:
            t = db.get(Transaction, r.link_txn_id)
            out.link = txn_out(t) if t else None
        rows.append(out)
    return StatementDetail(
        **_summary(imp).model_dump(),
        unparsed=imp.unparsed or [],
        rows=rows,
        account_suggested=account_suggested,
        overlaps=_overlaps(db, imp),
        figures=_figures(db, imp),
    )


def _overlaps(db: Session, imp: StatementImport) -> list[StatementOverlap]:
    """Other imports sharing most of this one's transactions (same date and
    amount): the same statement opened twice, e.g. from Gmail and as an upload.
    Needs at least 3 shared rows and over half of the smaller statement."""
    from collections import Counter

    mine = Counter((r.date, r.amount) for r in imp.rows)
    if sum(mine.values()) < 3:
        return []
    out = []
    others = db.scalars(
        select(StatementImport).where(StatementImport.id != imp.id).order_by(StatementImport.id.desc()).limit(200)
    )
    for o in others:
        theirs = Counter((r.date, r.amount) for r in o.rows)
        shared = sum((mine & theirs).values())
        if shared >= 3 and shared * 2 > min(sum(mine.values()), sum(theirs.values())):
            out.append(
                StatementOverlap(
                    id=o.id,
                    filename=o.filename,
                    source="upload" if o.upload_path else "email",
                    status=o.status,
                    shared_rows=shared,
                )
            )
    return out


def _get(db: Session, sid: int) -> StatementImport:
    imp = db.get(StatementImport, sid)
    if imp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Statement not found")
    return _revive(db, imp)


def _revive(db: Session, imp: StatementImport) -> StatementImport:
    """Bring an older statement up to date when it's opened again: if its account was deleted,
    match it to an account by the last 4 digits again; if transactions it imported were deleted
    since, those rows are read again (today's parser) to be imported once more."""
    changed = False
    # a statement imported before always had an account, so none now means it was deleted
    # (a never-imported draft without one may be your own choice: left alone)
    if imp.imported_at is not None and imp.account_id is None and imp.account_last4:
        account = _match_account(db, imp.account_last4, imp.doc_type)
        if account is not None:
            imp.account_id = account.id
            if account.type == AccountType.credit_card:
                imp.doc_type = "card_statement"
            changed = True
    if imp.status == "imported" and any(r.include and not r.transaction_id for r in imp.rows):
        changed = True  # transactions it imported were deleted (before they reopened it themselves)
    if changed:
        _rebuild(db, imp)  # also drops rows an older parser read wrongly
    elif imp.doc_type == "card_statement" and imp.statement_date is None:
        _apply_summary(imp)  # read before the summary box was understood
        changed = imp.statement_date is not None
    if changed:
        db.commit()
        db.refresh(imp)
    return imp


def _sender_key(att: GmailAttachment) -> str:
    """Remembered PDF passwords are keyed by the sender's domain."""
    addr = (att.message.from_addr or "").split("<")[-1].rstrip(">").strip()
    domain = addr.split("@")[-1].lower() if "@" in addr else "unknown"
    return f"pdf_password:{domain}"


def _match_account(db: Session, last4: str | None, doc_type: str | None = None) -> Account | None:
    """Your account whose number ends in the statement's last 4 digits — a card for
    a card statement, a bank or cash account for a bank statement (then any)."""
    if not last4:
        return None
    matches = []
    for a in db.scalars(select(Account).where(Account.type.in_(BALANCE_TYPES), Account.active.is_(True))):
        digits = "".join(ch for ch in (a.account_number or "") if ch.isdigit())
        if digits.endswith(last4):
            matches.append(a)
    want_card = doc_type == "card_statement"
    preferred = [a for a in matches if (a.type == AccountType.credit_card) == want_card]
    return (preferred or matches or [None])[0]


# ---------------------------------------------------------------- list / start


@router.get("", response_model=list[StatementSummary])
def list_statements(db: Session = Depends(get_db)) -> list[StatementSummary]:
    return [_summary(i) for i in db.scalars(select(StatementImport).order_by(StatementImport.id.desc()).limit(100))]


@router.post("", response_model=StatementDetail, status_code=201)
@one_at_a_time("statement-open")
def start_import(body: StatementStartIn, db: Session = Depends(get_db)) -> StatementDetail:
    """Read a statement PDF from the Inbox and create a draft import to review.
    Re-opening the same PDF returns the existing import."""
    att = db.get(GmailAttachment, body.attachment_id)
    if att is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    existing = db.scalar(
        select(StatementImport).where(StatementImport.attachment_id == att.id).order_by(StatementImport.id.desc())
    )
    if existing:
        return _detail(db, _revive(db, existing))
    if not (att.mime_type == "application/pdf" or att.filename.lower().endswith(".pdf")):
        raise _bad("Only PDF statements can be imported.", "not_pdf")

    text, parsed = _read_pdf(db, att, body.password, body.remember_password)
    account = _match_account(db, parsed.account_last4, parsed.doc_type)
    imp = StatementImport(
        gmail_message_id=att.message_id,
        attachment_id=att.id,
        filename=att.filename,
        doc_type=parsed.doc_type,
        account_last4=parsed.account_last4,
        account_id=account.id if account else None,
        text=text,
    )
    # Even with zero rows the draft is kept (with all its text), so a layout the
    # parser doesn't understand yet can be inspected and re-read after a fix.
    _fill_rows(imp, parsed, text)
    _apply_summary(imp)
    if not parsed.txns:
        log.warning("statement %s: no transactions found (%d text lines)", att.filename, len(text.splitlines()))
    db.add(imp)
    db.flush()
    refresh(db, imp)
    db.commit()
    db.refresh(imp)
    return _detail(db, imp, account_suggested=account is not None)


@router.post("/upload", response_model=StatementDetail, status_code=201)
@one_at_a_time("statement-open")
def upload_statement(body: StatementUploadIn, db: Session = Depends(get_db)) -> StatementDetail:
    """A statement PDF downloaded from your bank's website: same reading and
    review as one from the Inbox. Uploading the same file again opens its draft."""
    try:
        data = base64.b64decode(body.content_b64, validate=True)
    except (binascii.Error, ValueError):
        raise _bad("The file couldn't be read. Try choosing it again.", "bad_file") from None
    if len(data) > MAX_UPLOAD:
        raise _bad("That file is too big (over 15 MB). Statements are usually much smaller.", "too_big")
    if not data.startswith(b"%PDF"):
        raise _bad("Only PDF statements can be uploaded.", "not_pdf")
    account = None
    if body.account_id is not None:
        account = db.get(Account, body.account_id)
        if account is None or account.type not in BALANCE_TYPES:
            raise _bad("Pick one of your bank, cash or card accounts.", "bad_account")
    sha = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        select(StatementImport).where(StatementImport.file_sha256 == sha).order_by(StatementImport.id.desc())
    )
    if existing:
        return _detail(db, _revive(db, existing)).model_copy(update={"opened_existing": True})
    # The same file already fetched from Gmail: use that email's statement, so
    # the email is linked (and marked handled) as usual — no second draft.
    att = db.scalar(select(GmailAttachment).where(GmailAttachment.sha256 == sha).order_by(GmailAttachment.id))
    if att is not None and (attachments_dir() / att.path).exists():
        was_open = db.scalar(select(StatementImport.id).where(StatementImport.attachment_id == att.id)) is not None
        detail = start_import(
            StatementStartIn(attachment_id=att.id, password=body.password, remember_password=body.remember_password), db
        )
        if body.account_id is not None and not was_open and detail.account_id != body.account_id:
            detail = set_account(detail.id, StatementPatch(account_id=body.account_id), db)
        return detail.model_copy(update={"opened_existing": was_open})

    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(body.filename).name).strip() or "statement.pdf"
    rel = f"{sha[:16]}.pdf"
    path = uploads_dir() / rel
    path.write_bytes(data)
    try:
        text, parsed = _read_pdf_file(
            db,
            path,
            name,
            _account_key(body.account_id) or (CAS_PASSWORD_KEY if body.cas else None),
            body.password,
            body.remember_password,
            {"file_sha256": sha},
        )
    except HTTPException as e:
        if not (isinstance(e.detail, dict) and e.detail.get("code") == "loan_statement"):
            path.unlink(missing_ok=True)  # nothing kept until it opens
        raise
    matched = _match_account(db, parsed.account_last4, parsed.doc_type)
    chosen = account or matched
    imp = StatementImport(
        upload_path=rel,
        file_sha256=sha,
        filename=name,
        doc_type=parsed.doc_type,
        account_last4=parsed.account_last4,
        account_id=chosen.id if chosen else None,
        text=text,
    )
    if chosen is not None and chosen.type == AccountType.credit_card:
        imp.doc_type = "card_statement"  # you said it's a card statement
        if parsed.doc_type != "card_statement":
            parsed = parse_statement(text, "card_statement")
    _fill_rows(imp, parsed, text)
    _apply_summary(imp)
    if not parsed.txns:
        log.warning("statement %s: no transactions found (%d text lines)", name, len(text.splitlines()))
    db.add(imp)
    db.flush()
    refresh(db, imp)
    db.commit()
    db.refresh(imp)
    return _detail(db, imp, account_suggested=account is None and matched is not None)


def _read_pdf(db: Session, att: GmailAttachment, password: str | None, remember: bool):
    return _read_pdf_file(
        db,
        (attachments_dir() / att.path).resolve(),
        att.filename,
        _sender_key(att),
        password,
        remember,
        {"attachment_id": att.id, "file_sha256": att.sha256},
    )


def _cas_found(cas_id: int) -> HTTPException:
    """A mutual fund CAS: the page opens its review in Investments instead."""
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        {
            "code": "cas",
            "message": "This is a mutual fund statement (CAS) — opening it in Investments.",
            "cas_id": cas_id,
        },
    )


LOAN_PASSWORD_KEY = "pdf_password:loans"  # a loan statement uploaded from Loans
# A loan statement opened as a bank statement: its password, kept in memory for a few minutes
# so the loan review can read it without asking again (never stored).
_JUST_OPENED: dict[str, tuple[str, float]] = {}
JUST_OPENED_SECONDS = 600


def password_just_used(sha: str | None) -> str | None:
    now = time.monotonic()
    for k in [k for k, (_, t) in _JUST_OPENED.items() if now - t > JUST_OPENED_SECONDS]:
        del _JUST_OPENED[k]
    hit = _JUST_OPENED.get(sha or "")
    return hit[0] if hit else None


def _loan_found(source: dict | None) -> HTTPException:
    """A lender's loan statement: the page opens its review in Loans."""
    src = source or {}
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        {
            "code": "loan_statement",
            "message": "This is a loan statement — opening it in Loans.",
            "attachment_id": src.get("attachment_id"),
            "file_ref": src.get("file_sha256"),
        },
    )


def uploads_dir() -> Path:
    d = user_dir("uploads")
    d.mkdir(parents=True, exist_ok=True)
    return d


MAX_UPLOAD = 15 * 1024 * 1024  # 15 MB — statements are usually well under 1 MB


def _account_key(account_id: int | None) -> str | None:
    """Remembered passwords for uploaded PDFs are kept per account."""
    return f"pdf_password:account:{account_id}" if account_id else None


def _read_pdf_file(
    db: Session,
    path: Path,
    filename: str,
    key: str | None,
    password: str | None,
    remember: bool,
    source: dict | None = None,
):
    """Unlock + extract the PDF several ways and keep the extraction that parses
    best (most running balances that add up, then most rows). A mutual fund CAS
    becomes a CAS draft in Investments (`source`: attachment_id / file_sha256)."""
    from ..investments.models import CasImport  # investments imports the transactions module, not this one

    sha = (source or {}).get("file_sha256")
    if sha and (cas_id := db.scalar(select(CasImport.id).where(CasImport.file_sha256 == sha))):
        raise _cas_found(cas_id)  # opened before: no password needed again
    candidates, pw = unlock_pdf(db, path, filename, key, password, remember)
    if any(is_cas(text) for _, text in candidates):
        from ..investments.cas_service import open_draft

        cas = open_draft(db, candidates, filename, **(source or {}))
        db.commit()
        raise _cas_found(cas.id)
    if any(is_loan_statement(text) for _, text in candidates):
        if pw and sha:
            _JUST_OPENED[sha] = (pw, time.monotonic())
        db.commit()  # a password to remember
        raise _loan_found(source)
    best = None
    for method, text in candidates:
        parsed = parse_statement(text, "bank_statement")
        sc = score(parsed)
        log.info("statement %s: method=%s rows=%d balances_ok=%d mismatches=%d", filename, method, sc[2], sc[0], -sc[1])
        if best is None or sc > best[0]:
            best = (sc, method, text, parsed)
    log.info("statement %s: using %s", filename, best[1])
    return best[2], best[3]


def unlock_pdf(
    db: Session, path: Path, filename: str, key: str | None, password: str | None, remember: bool
) -> tuple[list[tuple[str, str]], str | None]:
    """Open the PDF (with the given or remembered password) and extract its text several
    ways. Returns the extractions and the password that opened it."""
    saved = db.get(Setting, key) if key else None
    remembered = None
    if saved:
        try:  # remembered passwords are stored encrypted
            remembered = json.loads(decrypt(saved.value))["password"]
        except (DecryptError, ValueError, KeyError):
            remembered = None
    pw = password or remembered
    try:
        candidates = extract_candidates(path, pw)
    except StatementError as e:
        log.warning("statement %s: %s (%s)", filename, e.code, e)
        if e.code == "wrong_password" and not password and remembered:
            raise _bad(
                "The remembered password no longer opens this PDF. Enter it again.", "password_required"
            ) from None
        raise _bad(str(e), e.code) from None
    if password and remember and key:
        row = saved or Setting(key=key, value="")
        row.value = encrypt(json.dumps({"password": password}))
        db.merge(row)
    return candidates, pw


@router.post("/{sid}/reread-pdf", response_model=StatementDetail)
def reread_pdf(sid: int, body: StatementRereadIn, db: Session = Depends(get_db)) -> StatementDetail:
    """Extract the PDF's text again (needs the password unless remembered) —
    for drafts read by an older version. Imported rows are kept."""
    imp = _get(db, sid)
    if imp.upload_path:
        path = uploads_dir() / imp.upload_path
        if not path.exists():
            raise _bad("The uploaded PDF is no longer on the server. Upload it again.", "missing_pdf")
        text, _ = _read_pdf_file(
            db, path, imp.filename, _account_key(imp.account_id), body.password, body.remember_password
        )
    else:
        att = db.get(GmailAttachment, imp.attachment_id) if imp.attachment_id else None
        if att is None:
            raise _bad("The original PDF is no longer in the Inbox.", "missing_pdf")
        text, _ = _read_pdf(db, att, body.password, body.remember_password)
    imp.text = text
    db.flush()
    return reparse(sid, db)


def _fill_rows(imp: StatementImport, parsed, text: str) -> None:
    start = max((r.idx for r in imp.rows), default=-1) + 1
    imp.unparsed = (parsed.unparsed if parsed.txns else [ln.strip() for ln in text.splitlines() if ln.strip()])[:800]
    for i, t in enumerate(parsed.txns, start):
        imp.rows.append(
            StatementRow(
                idx=i,
                date=datetime.fromisoformat(t.date).date(),
                amount=t.amount,
                description=t.description[:255] or "(no description)",
                raw=t.raw,
                counterparty=(t.counterparty or None) and t.counterparty[:120],
                name_hint=(t.name_hint or None) and t.name_hint[:120],
                balance=t.balance,
                kind="expense",
                payee="",
            )
        )


_CARRY = (
    "include",
    "keep_duplicate",
    "kind",
    "category_id",
    "budget_id",
    "transfer_account_id",
    "leave_uncategorised",
    "suggestion",
    "suggestion_kind",
    "create_rule",
    "rule_keyword",
)


def _row_key(r) -> tuple:
    # The running balance identifies a row even when the parser now reads its
    # description or amount differently; fall back to date + amount.
    return ("bal", r.balance) if r.balance is not None else ("amt", r.date, r.amount)


def _carry_edits(edited: list[StatementRow], rows: list[StatementRow]) -> int:
    """Copy your choices from the old rows onto the rebuilt ones. Payee only if
    you typed it (an auto-derived payee is derived again from the new text)."""
    by_key: dict[tuple, StatementRow] = {}
    for old in edited:
        by_key.setdefault(_row_key(old), old)
    carried = 0
    for new in rows:
        old = by_key.pop(_row_key(new), None)
        if old is None or new.transaction_id:
            continue
        for f in _CARRY:
            setattr(new, f, getattr(old, f))
        derived = payee_from(old.description, old.counterparty, old.name_hint)
        new.payee = (
            old.payee
            if old.payee and old.payee != derived
            else payee_from(new.description, new.counterparty, new.name_hint)
        )
        new.user_set = True
        carried += 1
    return carried


@router.post("/{sid}/reparse", response_model=StatementDetail)
def reparse(sid: int, db: Session = Depends(get_db)) -> StatementDetail:
    """Read the saved statement text again (e.g. after a parser fix) — no
    password needed. Rows already imported are kept; the rest are rebuilt."""
    imp = _rebuild(db, _get(db, sid))
    db.commit()
    db.refresh(imp)
    return _detail(db, imp)


def _rebuild(db: Session, imp: StatementImport) -> StatementImport:
    """Parse the saved text again with today's parser: rows that have a transaction stay,
    the others are rebuilt (your edits carried over); the summary box is read again."""
    current = db.get(Account, imp.account_id) if imp.account_id else None
    on_card = current is not None and current.type == AccountType.credit_card
    parsed = parse_statement(imp.text, "card_statement" if on_card else "bank_statement")
    kept_raw = {r.raw for r in imp.rows if r.transaction_id}
    edited = [r for r in imp.rows if r.user_set and not r.transaction_id]
    snapshot = [
        StatementRow(
            **{
                c: getattr(r, c)
                for c in ("balance", "date", "amount", "description", "counterparty", "name_hint", "payee", *_CARRY)
            }
        )
        for r in edited
    ]
    imp.rows = [r for r in imp.rows if r.transaction_id]
    # a row already imported stays; it's recognised by its text, or by date + amount when an
    # older parser read its text differently (e.g. with the next section's words stuck on)
    kept_keys = Counter((r.date.isoformat(), r.amount) for r in imp.rows if r.raw not in {t.raw for t in parsed.txns})
    fresh = []
    for t in parsed.txns:
        if t.raw in kept_raw:
            continue
        if kept_keys[(t.date, t.amount)] > 0:
            kept_keys[(t.date, t.amount)] -= 1
            continue
        fresh.append(t)
    parsed.txns = fresh
    imp.doc_type = "card_statement" if on_card else parsed.doc_type
    imp.account_last4 = parsed.account_last4 or imp.account_last4
    if imp.account_id is None:
        auto = _match_account(db, imp.account_last4, imp.doc_type)
        imp.account_id = auto.id if auto else None
    _fill_rows(imp, parsed, imp.text)
    _apply_summary(imp)
    carried = _carry_edits(snapshot, imp.rows)
    if carried:
        log.info("statement %s: kept your edits on %d of %d edited rows", imp.id, carried, len(snapshot))
    if parsed.txns or kept_raw:
        imp.status = "imported" if kept_raw and not parsed.txns else "draft"
    db.flush()
    refresh(db, imp)
    return imp


def reopen_imports(db: Session, import_ids: set[int]) -> None:
    """After transactions were deleted: statements that had imported them are read again,
    so those rows can be imported once more (as a draft). Called by the transactions module."""
    for imp in db.scalars(select(StatementImport).where(StatementImport.id.in_(import_ids))):
        if any(not r.transaction_id for r in imp.rows if r.include):
            _rebuild(db, imp)


@router.get("/{sid}", response_model=StatementDetail)
def get_statement(sid: int, db: Session = Depends(get_db)) -> StatementDetail:
    return _detail(db, _get(db, sid))


@router.patch("/{sid}", response_model=StatementDetail)
def set_account(sid: int, body: StatementPatch, db: Session = Depends(get_db)) -> StatementDetail:
    """Choose the account the statement belongs to (re-checks duplicates)."""
    imp = _get(db, sid)
    if body.account_id is not None:
        a = db.get(Account, body.account_id)
        if a is None or a.type not in BALANCE_TYPES:
            raise _bad("Choose one of your bank, cash or card accounts.")
        if a.type == AccountType.credit_card and imp.doc_type != "card_statement":
            imp.account_id = a.id
            if not any(r.transaction_id for r in imp.rows):
                db.flush()
                return reparse(sid, db)
            imp.doc_type = "card_statement"
            _apply_summary(imp)
    imp.account_id = body.account_id
    refresh(db, imp)
    db.commit()
    return _detail(db, imp)


@router.delete("/{sid}", status_code=204)
def discard(sid: int, db: Session = Depends(get_db)) -> None:
    """Discard a draft. Imported transactions are kept (delete them individually)."""
    imp = _get(db, sid)
    upload = imp.upload_path
    db.delete(imp)
    db.commit()
    if upload:
        (uploads_dir() / upload).unlink(missing_ok=True)


# ---------------------------------------------------------------- rows


@router.patch("/{sid}/rows/{rid}", response_model=StatementRowOut)
def edit_row(sid: int, rid: int, body: StatementRowPatch, db: Session = Depends(get_db)) -> StatementRowOut:
    imp = _get(db, sid)
    row = db.get(StatementRow, rid)
    if row is None or row.import_id != imp.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Row not found")
    if row.transaction_id:
        raise _bad("This row is already imported.")
    data = body.model_dump(exclude_unset=True)
    if "category_id" in data and data["category_id"] is not None and db.get(Category, data["category_id"]) is None:
        raise _bad("Category not found")
    if "budget_id" in data and data["budget_id"] is not None and db.get(Budget, data["budget_id"]) is None:
        raise _bad("Budget not found")
    if data.get("transfer_account_id") is not None:
        a = db.get(Account, data["transfer_account_id"])
        if a is None or a.type not in {str(t) for t in OWN_TYPES} or a.id == imp.account_id:
            raise _bad("Choose another of your own accounts for the transfer.")
    amount = data.get("amount", row.amount)
    kind = data.get("kind", row.kind)
    if amount == 0:
        raise _bad("Amount can't be zero.")
    if (kind == "expense" and amount > 0) or (kind == "income" and amount < 0):
        raise _bad("Money coming in is income and money going out is an expense — or choose transfer.")
    if "link_txn_id" in data and data["link_txn_id"] is not None:
        raise _bad("A link can only be removed here.")
    if "loan_id" in data and data["loan_id"] is not None:
        raise _bad("A loan link can only be removed here.")
    if "loan_id" in data:
        row.loan_action = None
    if "include" in data:  # ticking in a row shown as already recorded: you mean it
        row.keep_duplicate = bool(data["include"]) and row.duplicate_of is not None
    for k, v in data.items():
        setattr(row, k, v)
    # the link to an existing expense only holds for a transfer from that expense's account
    if row.link_txn_id:
        linked = db.get(Transaction, row.link_txn_id)
        if not row.include or row.kind != "transfer" or linked is None or row.transfer_account_id != linked.source_id:
            row.link_txn_id = None
    if "amount" in data and "kind" not in data and row.kind != "transfer":
        row.kind = "income" if row.amount > 0 else "expense"  # sign flipped by an edit
    if "category_id" in data:
        if data["category_id"] is not None:
            row.leave_uncategorised = False
        row.suggestion, row.suggestion_kind = None, None
    if data.get("leave_uncategorised"):
        row.category_id = None
    if row.create_rule and not (row.rule_keyword or "").strip():
        row.rule_keyword = row.payee[:120]  # "rule for next time": the payee unless you typed a word
    row.user_set = True
    db.commit()
    out = StatementRowOut.model_validate(row)
    out.status = row_status(row)
    return out


def _similar(imp: StatementImport, row: StatementRow) -> list[StatementRow]:
    """Other rows in this statement with the same payee and type that you
    haven't decided yourself and that don't already match this row."""
    key = payee_key(row.payee)
    out = []
    for r in imp.rows:
        if r.id == row.id or r.transaction_id or not r.include or r.user_set or r.kind != row.kind:
            continue
        if not key or payee_key(r.payee) != key:
            continue
        same = (
            (r.transfer_account_id == row.transfer_account_id)
            if row.kind == "transfer"
            else (r.category_id == row.category_id and r.leave_uncategorised == row.leave_uncategorised)
        )
        if not same:
            out.append(r)
    return out


@router.post("/{sid}/rows/{rid}/apply-similar", response_model=StatementDetail)
def apply_to_similar(sid: int, rid: int, db: Session = Depends(get_db)) -> StatementDetail:
    """Copy this row's category (or transfer account) and budget to the other
    rows with the same payee and type in this statement."""
    imp = _get(db, sid)
    row = db.get(StatementRow, rid)
    if row is None or row.import_id != imp.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Row not found")
    if row.kind == "transfer" and row.transfer_account_id is None:
        raise _bad("Choose the account on this row first.")
    if row.kind != "transfer" and row.category_id is None and not row.leave_uncategorised:
        raise _bad("Choose a category on this row first.")
    for r in _similar(imp, row):
        if row.kind == "transfer":
            r.transfer_account_id = row.transfer_account_id
        else:
            r.category_id, r.leave_uncategorised, r.budget_id = row.category_id, row.leave_uncategorised, row.budget_id
            r.suggestion, r.suggestion_kind = f"Same as {row.date:%d %b} row", None
        r.user_set = True
    db.commit()
    db.refresh(imp)
    return _detail(db, imp)


# ---------------------------------------------------------------- import


@router.post("/{sid}/import", response_model=StatementImportOut)
@one_at_a_time("statement-import")
def do_import(sid: int, db: Session = Depends(get_db)) -> StatementImportOut:
    """Create transactions for every ready row.
    Refused while any included row still needs a category or transfer account."""
    imp = _get(db, sid)
    account = db.get(Account, imp.account_id) if imp.account_id else None
    if account is None:
        raise _bad("Choose which account this statement belongs to first.", "needs_account")
    pending = [r for r in imp.rows if row_status(r) in ("needs_category", "needs_account")]
    if pending:
        raise _bad(f"{len(pending)} row(s) still need a category or a transfer account.", "unresolved")

    from ..rules.engine import active_rules, apply_plan, plan_for, probe_of

    rules = active_rules(db)
    imported = 0
    for row in imp.rows:
        st = row_status(row)
        if st == "link":
            # the bank-side expense becomes the bank -> card transfer
            t = db.get(Transaction, row.link_txn_id)
            if t is not None and t.type == TransactionType.withdrawal.value:
                t.type = TransactionType.transfer.value
                t.destination_id = account.id
                t.category_id = None
                t.budget_id = None
                t.bill_id = None
                db.flush()
                row.transaction_id = t.id
                imported += 1
                continue
            row.link_txn_id = None
            if (
                t is not None
                and t.type == TransactionType.transfer.value
                and account.id in (t.source_id, t.destination_id)
            ):
                # already turned into this card's transfer (e.g. on the Credit cards page): nothing to add
                row.duplicate_of, row.include = t.id, False
                continue
            st = row_status(row)  # the expense changed meanwhile: import the row as usual
        if st != "ready":
            continue
        out = row.amount < 0
        body: dict = {
            "date": row.date,
            "amount": abs(row.amount),
            "description": row.description,
            "gmail_message_id": imp.gmail_message_id,
        }
        if row.kind == "transfer":
            body.update(
                type=TransactionType.transfer,
                source_id=account.id if out else row.transfer_account_id,
                destination_id=row.transfer_account_id if out else account.id,
            )
        elif row.kind == "income":
            body.update(
                type=TransactionType.deposit,
                source_name=row.payee,
                destination_id=account.id,
                category_id=row.category_id,
            )
        else:
            body.update(
                type=TransactionType.withdrawal,
                source_id=account.id,
                destination_name=row.payee,
                category_id=row.category_id,
                budget_id=row.budget_id,
            )
        t = Transaction()
        apply_body(db, t, TransactionIn(**body), is_new=True)
        t.emi_id = row.emi_id  # card EMI instalment / interest / conversion
        db.add(t)
        db.flush()
        db.refresh(t)
        row.transaction_id = t.id
        if rules:  # tags, bill, notes from your rules (category and payee were settled on the review page)
            plan = plan_for(probe_of(t), rules)
            if plan.rules:
                apply_plan(db, t, plan, overwrite=False, skip={"category_id", "budget_id"})
        if row.loan_id and row.kind == "expense" and (loan := db.get(Loan, row.loan_id)) is not None:
            # a loan's EMI (split for interest-only loans) or a part-payment on it
            if row.loan_action == "emi":
                link_payments(db, loan, [t])
            else:
                record_prepay(db, loan, t.date, t.amount, "reduce_tenure", existing=t)
        imported += 1

    rules_created = _rules_for_next_time(db, imp)
    imp.imported_count += imported
    imp.status = "imported"
    imp.imported_at = datetime.now()
    sync_inbox_status(db, imp.gmail_message_id)
    db.commit()
    db.refresh(imp)
    return StatementImportOut(imported=imported, rules_created=rules_created, statement=_detail(db, imp))


def _rules_for_next_time(db: Session, imp: StatementImport) -> int:
    """The rows you ticked "rule for next time": a rule "payee contains <keyword> -> category"
    (one per keyword; none if a rule already does the same)."""
    from ..rules.engine import Probe, active_rules, plan_for
    from ..rules.models import Rule

    made = 0
    for row in imp.rows:
        keyword = (row.rule_keyword or "").strip()
        if not (row.create_rule and row.transaction_id and row.category_id and keyword):
            continue
        row.create_rule = False
        typ = "withdrawal" if row.kind == "expense" else "deposit"
        probe = Probe(type=typ, amount=abs(row.amount), description=keyword, payee=keyword, account_ids=set())
        if plan_for(probe, active_rules(db)).category_id == row.category_id:
            continue  # already covered
        cat = db.get(Category, row.category_id)
        last = db.scalar(select(func.max(Rule.position))) or 0
        db.add(
            Rule(
                title=f"{keyword} → {cat.name if cat else 'category'}"[:120],
                position=last + 1,
                conditions=[{"type": "payee_contains", "value": keyword[:255]}, {"type": "type_is", "value": typ}],
                actions=[{"type": "set_category", "value": row.category_id}],
            )
        )
        db.flush()
        made += 1
    return made

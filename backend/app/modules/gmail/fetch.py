"""Query building (India pack templates), size estimate + consent, fetching."""

import base64
import hashlib
import html
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...db import SessionLocal
from . import client as gclient
from .models import GmailAttachment, GmailMessage, GmailRun

log = logging.getLogger("moneymap.gmail")
PACK_DIR = Path(__file__).resolve().parents[3] / "packs" / "in"  # backend/packs/in
BASE_EXCLUSIONS = ["-in:spam", "-in:trash"]
MAX_BODY_CHARS = 20_000
RUN_INLINE = False  # tests set True to run fetches synchronously


def consent_threshold() -> int:
    """Fetches estimated above this many bytes need a tick to confirm."""
    return get_settings().gmail_consent_mb * 1_000_000


def attachments_dir() -> Path:
    d = get_settings().data_dir / "gmail"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- templates


@lru_cache
def templates() -> list[dict]:
    path = PACK_DIR / "gmail-templates.json"
    return json.loads(path.read_text(encoding="utf8")).get("templates", []) if path.exists() else []


@lru_cache
def provider_names() -> dict[str, str]:
    names: dict[str, str] = {"cams": "CAMS (mutual fund CAS)", "kfintech": "KFintech (mutual fund CAS)"}
    for fname, key in (("banks.json", "providers"), ("credit-cards.json", "issuers")):
        path = PACK_DIR / fname
        if path.exists():
            for p in json.loads(path.read_text(encoding="utf8")).get(key, []):
                names[p["id"]] = p["display_name"]
    return names


def provider_options() -> list[dict]:
    """Template list for the UI: one entry per template."""
    names = provider_names()
    kind = {
        "bank_statement": "Bank statement",
        "credit_card_statement": "Credit card statement",
        "loan_statement": "Loan statement",
        "mf_statement": "Mutual fund statement (CAS)",
        "transaction_alert": "Transaction alerts",
    }
    return [
        {
            "id": t["id"],
            "provider_id": t["provider_id"],
            "name": t.get("name") or names.get(t["provider_id"], t["provider_id"]),
            "doc_type": kind.get(t["doc_type"], t["doc_type"]),
            "kind": t["doc_type"],
        }
        for t in templates()
    ]


def gmail_date(d: date) -> str:
    return d.strftime("%Y/%m/%d")


def build_queries(template_ids: list[str], custom: list[str], date_from: date, date_to: date) -> list[dict]:
    """One Gmail query per chosen template / custom line, scoped to the window.
    Gmail's before: is exclusive, so it gets the day after date_to."""
    window = [f"after:{gmail_date(date_from)}", f"before:{gmail_date(date_to + timedelta(days=1))}"]
    by_id = {t["id"]: t for t in templates()}
    names = provider_names()
    out, seen = [], set()

    def add(label: str, provider: str | None, fragments: list[str], doc_type: str | None = None) -> None:
        parts: list[str] = []
        for f in [*fragments, *BASE_EXCLUSIONS, *window]:
            f = f.strip()
            if f and f not in parts:
                parts.append(f)
        q = " ".join(parts)
        if q not in seen:
            seen.add(q)
            out.append({"label": label, "provider_id": provider, "doc_type": doc_type, "query": q})

    for tid in template_ids:
        t = by_id.get(tid)
        if t is None:
            raise gclient.GmailError(f"Unknown template {tid!r}")
        label = t.get("name") or names.get(t["provider_id"], t["provider_id"])
        if t["doc_type"] == "transaction_alert":
            label += " · alerts"
        elif t["doc_type"] == "loan_statement":
            label += " · loan"
        add(label, t["provider_id"], t.get("query_fragments", []), t["doc_type"])
    for line in custom:
        line = line.strip()
        if not line:
            continue
        if re.search(r"\b(after|before|older_than|newer_than):", line):
            raise gclient.GmailError(f"Leave dates out of custom queries — the date range is added for you: {line!r}")
        add(f"Custom: {line}", None, [line])
    if not out:
        raise gclient.GmailError("Choose at least one bank/card or add a custom query.")
    return out


def human_bytes(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.0f} {unit}" if unit == "B" or v >= 10 else f"{v:.1f} {unit}"
        v /= 1024
    return f"{n} B"


# ---------------------------------------------------------------- estimate


_LAST4_ANY = re.compile(
    r"(?:a/c|acct|account|card|ac)\s*(?:no\.?|number|ending(?:\s+(?:with|in))?)?\s*[:.-]?\s*(?:[x*]+\s*)?([0-9]{4})\b"
    r"|\b(?:x{2,}|\*{2,})\s*([0-9]{4})\b"
    r"|\bending\s+(?:with\s+|in\s+)?([0-9]{4})\b"
    r"|(?:a/c|acct|account)\s*(?:no\.?|number)\s*[:.-]?\s*[0-9]{4,}([0-9]{4})\b",
    re.I,
)


def last4_of(text: str) -> str | None:
    """The last 4 digits of an account / card in a subject or preview: "A/c XX1234", "card ending 5678",
    "xxxx9012", "**3456"."""
    m = _LAST4_ANY.search(text or "")
    return next((g for g in m.groups() if g), None) if m else None


def _last4_owners(db: Session) -> dict[str, str]:
    """last 4 digits -> the account or card's name (bank account numbers and card last4)."""
    from ..accounts.models import Account
    from ..cards.models import CreditCard

    out: dict[str, str] = {}
    for a in db.scalars(select(Account).where(Account.account_number.is_not(None))):
        digits = re.sub(r"\D", "", a.account_number or "")
        if len(digits) >= 4:
            out.setdefault(digits[-4:], a.name)
    for c in db.scalars(select(CreditCard).where(CreditCard.last4.is_not(None))):
        acct = db.get(Account, c.account_id)
        out.setdefault(c.last4, acct.name if acct else f"Card {c.last4}")
    return out


def estimate(db: Session, template_ids: list[str], custom: list[str], date_from: date, date_to: date) -> GmailRun:
    """List matching ids per query and, for the new ones, their sender, subject, date and size
    (headers only — nothing downloaded), so you can pick what to fetch. Ones already in the Inbox
    are listed too, from what's stored."""
    if date_to < date_from:
        raise gclient.GmailError("The end date is before the start date.")
    queries = build_queries(template_ids, custom, date_from, date_to)
    api = gclient.api_for(db)
    known = set(db.scalars(select(GmailMessage.id)))
    pending: list[list] = []
    hits: list[tuple[str, int]] = []
    seen: set[str] = set()
    matched = 0
    for qi, q in enumerate(queries):
        for mid in api.list_ids(q["query"]):
            if mid in seen:
                continue
            seen.add(mid)
            matched += 1
            hits.append((mid, qi))
            if mid not in known:
                pending.append([mid, qi])
    # Refresh the token once up front: the worker threads must not each try
    # to refresh it (they share one DB session).
    getattr(api, "_token", lambda: None)()
    with ThreadPoolExecutor(max_workers=8) as pool:
        metas = dict(
            zip([p[0] for p in pending], pool.map(lambda p: api.get_message(p[0], "metadata"), pending), strict=True)
        )
    sizes = [int(m.get("sizeEstimate", 0)) for m in metas.values()]
    found = []
    for mid, qi in hits:
        if mid in metas:
            m = metas[mid]
            payload = m.get("payload", {})
            sent = datetime.fromtimestamp(int(m["internalDate"]) / 1000) if m.get("internalDate") else None
            found.append({
                "id": mid, "q": qi, "from": _header(payload, "From"), "subject": _header(payload, "Subject"),
                "date": sent.isoformat(timespec="minutes") if sent else None,
                "size": int(m.get("sizeEstimate", 0)), "known": False,
            })  # fmt: skip
        else:
            g = db.get(GmailMessage, mid)
            found.append({
                "id": mid, "q": qi, "from": g.from_addr if g else None, "subject": g.subject if g else None,
                "date": g.sent_at.isoformat(timespec="minutes") if g and g.sent_at else None,
                "size": g.size_estimate if g else 0, "known": True,
            })  # fmt: skip
    # which account / card each one is for: the last 4 digits in the subject or the preview text
    snippets = {mid: m.get("snippet") for mid, m in metas.items()}
    owners = _last4_owners(db)
    for f in found:
        g = None if f["id"] in snippets else db.get(GmailMessage, f["id"])
        text = f"{f['subject'] or ''} {html.unescape(snippets.get(f['id']) or (g.snippet if g else '') or '')}"
        f["last4"] = last4_of(text)
        f["account"] = owners.get(f["last4"]) if f["last4"] else None
    found.sort(key=lambda f: (f["q"], f["date"] or ""), reverse=False)
    run = GmailRun(
        status="estimated",
        date_from=date_from,
        date_to=date_to,
        queries=queries,
        pending_ids=pending,
        found=found,
        matched_count=matched,
        new_count=len(pending),
        bytes_estimated=int(sum(sizes)),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# ---------------------------------------------------------------- message parsing


def _header(payload: dict, name: str) -> str | None:
    for h in payload.get("headers", []) or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


def _decode(data: str | None) -> str:
    if not data:
        return ""
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    return raw.decode("utf-8", errors="replace")


def _html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def extract(payload: dict) -> tuple[str, list[dict]]:
    """Plain-text body (text/plain preferred, else stripped HTML) and attachment parts."""
    plain, htmls, atts = [], [], []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        body = part.get("body", {}) or {}
        if part.get("filename") and body.get("attachmentId"):
            atts.append(part)
        elif mime == "text/plain" and body.get("data"):
            plain.append(_decode(body["data"]))
        elif mime == "text/html" and body.get("data"):
            htmls.append(_decode(body["data"]))
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    text = "\n".join(plain).strip() or _html_to_text("\n".join(htmls))
    return text[:MAX_BODY_CHARS], atts


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[-120:] or "attachment"


def store_message(db: Session, api, mid: str, query: dict, run: GmailRun) -> tuple[int, int]:
    """Fetch one message + its attachments into the DB/disk. Returns (attachments, bytes)."""
    msg = api.get_message(mid, "full")
    payload = msg.get("payload", {}) or {}
    body, parts = extract(payload)
    sent = datetime.fromtimestamp(int(msg["internalDate"]) / 1000) if msg.get("internalDate") else None
    m = GmailMessage(
        id=mid,
        thread_id=msg.get("threadId"),
        run_id=run.id,
        from_addr=(_header(payload, "From") or "")[:320] or None,
        subject=(_header(payload, "Subject") or "")[:500] or None,
        sent_at=sent,
        snippet=html.unescape(msg.get("snippet") or "") or None,
        body_text=body or None,
        provider_id=query.get("provider_id"),
        doc_type=query.get("doc_type"),
        matched_query=query.get("query"),
        size_estimate=msg.get("sizeEstimate", 0),
        status="new",
    )
    db.add(m)
    count = nbytes = 0
    folder = attachments_dir()
    for part in parts:
        data = api.get_attachment(mid, part["body"]["attachmentId"])
        sha = hashlib.sha256(data).hexdigest()
        ext = Path(part.get("filename") or "").suffix[:10] or ".bin"
        rel = f"{sha}{_safe_name(ext)}"
        path = folder / rel
        if not path.exists():  # same file in several emails is stored once
            path.write_bytes(data)
        m.attachments.append(
            GmailAttachment(
                filename=(part.get("filename") or "attachment")[:255],
                mime_type=part.get("mimeType"),
                size=len(data),
                sha256=sha,
                path=rel,
            )
        )
        count += 1
        nbytes += len(data)
    return count, nbytes


# ---------------------------------------------------------------- fetch


def start_fetch(db: Session, run: GmailRun, consent: bool, ids: list[str] | None = None) -> GmailRun:
    """Download the new emails found — only `ids` when you picked some."""
    if run.status != "estimated":
        raise gclient.GmailError(f"This fetch is already {run.status}.")
    if ids is not None:
        keep = set(ids)
        run.pending_ids = [p for p in run.pending_ids if p[0] in keep]
        if not run.pending_ids:
            raise gclient.GmailError("Tick at least one email to fetch.")
        run.new_count = len(run.pending_ids)
        run.bytes_estimated = sum(f.get("size", 0) for f in run.found or [] if f["id"] in keep and not f.get("known"))
    if run.bytes_estimated > consent_threshold() and not consent:
        raise gclient.GmailError(
            f"This would download about {human_bytes(run.bytes_estimated)}. Tick the confirmation to continue."
        )
    run.status = "running"
    run.started_at = datetime.now()
    run.progress = "Starting…"
    db.commit()
    if RUN_INLINE:
        _fetch_worker(run.id)
    else:
        threading.Thread(target=_fetch_worker, args=(run.id,), daemon=True, name=f"gmail-run-{run.id}").start()
    return run


def _fetch_worker(run_id: int) -> None:
    with SessionLocal() as db:
        run = db.get(GmailRun, run_id)
        try:
            api = gclient.api_for(db)
            total = len(run.pending_ids)
            remaining = list(run.pending_ids)
            for i, (mid, qi) in enumerate(list(remaining), 1):
                db.refresh(run)
                if run.status == "cancelling":
                    run.status = "cancelled"
                    break
                if db.get(GmailMessage, mid) is None:
                    n, b = store_message(db, api, mid, run.queries[qi], run)
                    run.message_count += 1
                    run.attachment_count += n
                    run.bytes_downloaded += b
                remaining.pop(0)
                run.pending_ids = list(remaining)
                run.progress = f"Fetched {i} of {total} emails"
                db.commit()
            else:
                run.status = "done"
                run.progress = f"Fetched {run.message_count} email(s), {run.attachment_count} attachment(s)"
                acct = gclient.account(db)
                if acct and (acct.last_fetch_to is None or run.date_to > acct.last_fetch_to):
                    acct.last_fetch_to = run.date_to
            run.finished_at = datetime.now()
            db.commit()
        except Exception as e:  # keep what was fetched; report the error
            db.rollback()
            run = db.get(GmailRun, run_id)
            run.status = "error"
            run.error = str(e)
            run.finished_at = datetime.now()
            db.commit()
            log.exception("gmail run %s failed", run_id)


def recover_stuck_runs() -> None:
    """A restart kills fetch threads; mark their runs so the UI doesn't spin."""
    with SessionLocal() as db:
        for run in db.scalars(select(GmailRun).where(GmailRun.status.in_(["running", "cancelling"]))):
            run.status = "error"
            run.error = "Interrupted by a restart. Start a new fetch — emails already fetched are kept and skipped."
            run.finished_at = datetime.now()
        db.commit()

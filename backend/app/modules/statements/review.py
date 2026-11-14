"""Turn parsed rows into a reviewable import: payee, kind, suggested category
(from your history for the same payee), duplicates, status."""

import re
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..accounts.models import Account
from ..categories.models import Category
from ..transactions.models import Transaction
from .models import StatementImport, StatementRow

RAIL_WORDS = {
    "upi",
    "neft",
    "imps",
    "rtgs",
    "pos",
    "ecom",
    "ach",
    "nach",
    "enach",
    "ecs",
    "bil",
    "cms",
    "atm",
    "mmt",
    "vps",
    "inft",
    "ift",
    "dr",
    "cr",
    "ref",
    "txn",
    "payment",
    "to",
    "from",
    "by",
    "the",
    "via",
    "transfer",
    "bank",
    "ltd",
    "pvt",
    "india",
    "in",
    "and",
    "of",
    "mb",
    "ib",
    "onl",
    "online",
}
TRANSFER_RE = re.compile(
    r"payment received|thank you for (the )?payment|cc payment|credit card payment|card payment|autopay|"
    r"bbps.*(card|cc)|infinity payment|payment.*credit card",
    re.I,
)


# ---------------------------------------------------------------- payee


def payee_from(description: str, counterparty: str | None, name_hint: str | None = None) -> str:
    """A short, stable payee name for a statement line. A payee name the bank
    prints on its own line (ICICI) beats anything derived from the narration."""
    if name_hint and name_hint.strip():
        return name_hint.strip().title()[:120]
    # ICICI/HDFC rail lines: UPI/<NAME>/<vpa>/<note>/<bank> — the name segment
    # reads better than the UPI id and is what you'd call the payee.
    for chunk in re.findall(r"\b(?:upi|neft|imps|rtgs|bil|pos|ecom)/[^ ]*(?: [^ /]+/[^ ]*)*", description, re.I):
        parts = [p.strip() for p in chunk.split("/")]
        for p in parts[1:]:
            if re.search(r"[A-Za-z]{3,}", p) and not re.search(r"\d{4,}|@", p):
                return p.title()[:120]
    if counterparty:
        return counterparty[:120]
    words = []
    for w in re.split(r"[\s/|*\-_,.:#()]+", description):
        lw = w.lower()
        if not w or lw in RAIL_WORDS or re.search(r"\d", w) or "@" in w or len(w) < 2:
            continue
        words.append(w)
        if len(words) == 3:
            break
    return (" ".join(words).title() or description[:40] or "Unknown")[:120]


def payee_key(name: str) -> str:
    return re.sub(r"[^a-z0-9@.]+", " ", name.lower()).strip()


# ---------------------------------------------------------------- suggestions


def suggest_from_history(db: Session, row: StatementRow) -> tuple[int | None, int | None, str | None]:
    """The category you used most recently for the same payee."""
    if row.kind == "transfer":
        return None, None, None
    expense = row.kind == "expense"
    side = Transaction.destination_id if expense else Transaction.source_id
    payee_ids = select(Account.id).where(
        Account.type == ("expense" if expense else "revenue"), func.lower(Account.name) == row.payee.lower()
    )
    q = (
        select(Transaction)
        .where(side.in_(payee_ids), Transaction.category_id.is_not(None))
        .order_by(Transaction.date.desc(), Transaction.id.desc())
    )
    past = list(db.scalars(q.limit(50)).unique())
    if not past:
        return None, None, None
    latest = past[0]
    return (
        latest.category_id,
        latest.budget_id if expense else None,
        f"Like {len(past)} past {row.payee} transaction{'s' if len(past) != 1 else ''}",
    )


def find_duplicate(db: Session, row: StatementRow, account_id: int, claimed: set[int]) -> int | None:
    """An existing transaction on this account with the same amount within ±2 days."""
    q = select(Transaction.id).where(
        or_(Transaction.source_id == account_id, Transaction.destination_id == account_id),
        Transaction.amount == abs(row.amount),
        Transaction.date >= row.date - timedelta(days=2),
        Transaction.date <= row.date + timedelta(days=2),
    )
    for tid in db.scalars(q.order_by(Transaction.date)):
        if tid not in claimed:
            return tid
    return None


def refresh(db: Session, imp: StatementImport) -> None:
    """(Re)compute payee/kind/suggestions/duplicates for rows you haven't edited."""
    account = db.get(Account, imp.account_id) if imp.account_id else None
    claimed: set[int] = {r.transaction_id for r in imp.rows if r.transaction_id}
    for row in imp.rows:
        if row.transaction_id:  # already imported
            continue
        if not row.user_set:
            row.payee = payee_from(row.description, row.counterparty, row.name_hint)
            row.kind = "transfer" if TRANSFER_RE.search(row.raw) else ("income" if row.amount > 0 else "expense")
            cat, bud, why = suggest_from_history(db, row)
            kind = "history" if why else None
            row.category_id, row.budget_id, row.suggestion, row.suggestion_kind = cat, bud, why, kind
        row.duplicate_of = None
        if account is not None:
            dup = find_duplicate(db, row, account.id, claimed)
            if dup:
                row.duplicate_of = dup
                claimed.add(dup)
        if not row.user_set:
            row.include = row.duplicate_of is None


def row_status(row: StatementRow) -> str:
    if row.transaction_id:
        return "imported"
    if not row.include:
        return "duplicate" if row.duplicate_of else "skipped"
    if row.kind == "transfer":
        return "ready" if row.transfer_account_id else "needs_account"
    if row.category_id or row.leave_uncategorised:
        return "ready"
    return "needs_category"


def category_exists(db: Session, cid: int | None) -> bool:
    return cid is None or db.get(Category, cid) is not None

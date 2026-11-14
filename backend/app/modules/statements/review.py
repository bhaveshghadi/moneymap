"""Turn parsed rows into a reviewable import: payee, kind, suggested category
(from your history for the same payee), duplicates, status.

On a credit card statement: purchases are expenses from the card, refunds and
cashback are income into it, fees and interest get the Card Fees & Interest
category, and "payment received" is a transfer bank -> card. A payment already
recorded on the bank side as an expense (e.g. a CRED payment) is linked: the
import turns that expense into the transfer instead of adding it twice."""

import re
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..accounts.models import Account, AccountType
from ..cards.emi import CONVERSION_RE, GST_RE, INTEREST_RE, PRINCIPAL_RE, match_plan, plans_of
from ..cards.models import CardEmi
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
# Bank side: paying a card through CRED and similar apps.
CARD_APP_RE = re.compile(r"\bcred\b|cred\s*club|credclub", re.I)
# Card side
FEE_RE = re.compile(
    r"\b(interest|finance charges?|late (payment )?(fee|charges?)|annual (fee|membership)|membership fee|"
    r"renewal fee|joining fee|over ?limit|cash (advance|withdrawal) (fee|charges?)|fuel surcharge|surcharge|"
    r"mark ?up|cross currency|forex|igst|cgst|sgst|gst|service tax)\b",
    re.I,
)
CASHBACK_RE = re.compile(r"cash ?back|reward", re.I)
EMI_RE = re.compile(r"\bemi\b|equated|loan on card|insta ?loan|principal|converted to", re.I)
FEE_CATEGORY = "Card Fees & Interest"
LINK_DAYS = 3


def is_card_payment_text(text: str) -> bool:
    return bool(TRANSFER_RE.search(text) or CARD_APP_RE.search(text))


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


def _category_id(db: Session, name: str) -> int | None:
    return db.scalar(select(Category.id).where(func.lower(Category.name) == name.lower()))


def _active(db: Session, type_: AccountType) -> list[Account]:
    return list(db.scalars(select(Account).where(Account.type == type_.value, Account.active.is_(True))))


def suggest_transfer_account(db: Session, account: Account, row: StatementRow) -> tuple[int | None, str | None]:
    """The other side of a card bill payment: on a card statement, the bank you paid
    this card from last time (or your only bank account); on a bank statement, the
    card whose last 4 digits appear in the line (or your only card)."""
    if account.type == AccountType.credit_card:
        last = db.scalar(
            select(Transaction.source_id)
            .join(Account, Transaction.source_id == Account.id)
            .where(
                Transaction.destination_id == account.id,
                Transaction.type == "transfer",
                Account.type.in_(("asset", "cash")),
            )
            .order_by(Transaction.date.desc(), Transaction.id.desc())
            .limit(1)
        )
        if last:
            return last, "The account you paid this card from last time"
        banks = _active(db, AccountType.asset)
        if len(banks) == 1:
            return banks[0].id, "Your only bank account"
        return None, None
    if row.amount >= 0:
        return None, None
    cards = _active(db, AccountType.credit_card)
    digits = re.sub(r"\D", " ", row.raw)
    for c in cards:
        num = (c.account_number or "")[-4:]
        if num and re.search(rf"(?<!\d){num}(?!\d)", digits):
            return c.id, f"Card ending {num} is in the description"
    if len(cards) == 1:
        return cards[0].id, "Your only credit card"
    return None, None


def find_bank_side_expense(db: Session, row: StatementRow, claimed: set[int]) -> Transaction | None:
    """A card payment already recorded as an EXPENSE from a bank or cash account
    (same amount, within 3 days, card-payment words or a card category)."""
    q = (
        select(Transaction)
        .join(Account, Transaction.source_id == Account.id)
        .where(
            Transaction.type == "withdrawal",
            Account.type.in_(("asset", "cash")),
            Transaction.amount == abs(row.amount),
            Transaction.date >= row.date - timedelta(days=LINK_DAYS),
            Transaction.date <= row.date + timedelta(days=LINK_DAYS),
        )
        .order_by(Transaction.date)
    )
    for t in db.scalars(q).unique():
        if t.id in claimed:
            continue
        text = f"{t.description} {t.destination.name}"
        if is_card_payment_text(text) or (t.category and "card" in t.category.name.lower()):
            return t
    return None


def _emi_rows(row: StatementRow, plans: list[CardEmi], interest_days: dict) -> bool:
    """Card EMI rows: an instalment's principal becomes a transfer card -> plan, the
    "converted to EMI" credit a transfer plan -> card, and interest / GST are linked to
    the plan. True when the row was settled here (an instalment or a conversion)."""
    if row.amount < 0 and (m := PRINCIPAL_RE.search(row.raw)):
        plan = match_plan(plans, int(m.group(2)), m.group(3))
        if plan:
            row.kind, row.transfer_account_id, row.emi_id = "transfer", plan.account_id, plan.id
            row.category_id = row.budget_id = None
            row.suggestion, row.suggestion_kind = f"EMI instalment {m.group(1)}/{m.group(2)} · {plan.name}", "emi"
            return True
        row.flag = "emi"
        row.suggestion, row.suggestion_kind = "EMI instalment — add the EMI on the card page to match it", None
        return False
    if row.amount < 0 and (m := INTEREST_RE.search(row.raw)):
        plan = match_plan(plans, int(m.group(2)), m.group(3))
        if plan:
            row.emi_id = plan.id
            interest_days[row.date] = plan.id
        return False
    if row.amount < 0 and row.date in interest_days and GST_RE.search(row.raw):
        row.emi_id = interest_days[row.date]
        return False
    if row.amount > 0 and CONVERSION_RE.search(row.raw):
        plan = next((p for p in plans if p.closed_on is None and abs(p.principal - row.amount) <= 100), None)
        if plan:
            row.kind, row.transfer_account_id, row.emi_id = "transfer", plan.account_id, plan.id
            row.category_id = row.budget_id = None
            row.suggestion, row.suggestion_kind = f"Converted to EMI · {plan.name}", "emi"
            return True
    return False


def _suggest(
    db: Session,
    account: Account | None,
    row: StatementRow,
    plans: list[CardEmi] | None = None,
    interest_days: dict | None = None,
) -> None:
    """Kind, category and transfer account for a row you haven't edited."""
    row.payee = payee_from(row.description, row.counterparty, row.name_hint)
    row.flag = None
    row.transfer_account_id = None
    row.emi_id = None
    card = account is not None and account.type == AccountType.credit_card
    if card:
        if row.amount > 0 and TRANSFER_RE.search(row.raw):
            row.kind = "transfer"
        else:
            row.kind = "income" if row.amount > 0 else "expense"
    elif TRANSFER_RE.search(row.raw) or (row.amount < 0 and CARD_APP_RE.search(row.raw)):
        row.kind = "transfer"
    else:
        row.kind = "income" if row.amount > 0 else "expense"

    cat, bud, why = suggest_from_history(db, row)
    kind = "history" if why else None
    if card and row.kind == "expense" and FEE_RE.search(row.raw):
        cat, bud, why, kind = _category_id(db, FEE_CATEGORY), None, "Card fee or interest", "card"
    elif card and row.kind == "income" and not cat:
        name = "Cashback" if CASHBACK_RE.search(row.raw) else "Refund"
        cat, why, kind = _category_id(db, name), f"{name} on the card", "card"
    if row.kind == "transfer" and account is not None:
        row.transfer_account_id, tw = suggest_transfer_account(db, account, row)
        why, kind = tw, ("card" if tw else None)
    row.category_id, row.budget_id, row.suggestion, row.suggestion_kind = cat, bud, why, kind
    if card and _emi_rows(row, plans or [], interest_days if interest_days is not None else {}):
        return
    if card and row.emi_id is None and row.flag is None and EMI_RE.search(row.raw):
        row.flag = "emi"


def refresh(db: Session, imp: StatementImport) -> None:
    """(Re)compute payee/kind/suggestions/duplicates for rows you haven't edited."""
    account = db.get(Account, imp.account_id) if imp.account_id else None
    claimed: set[int] = {r.transaction_id for r in imp.rows if r.transaction_id}
    claimed |= {r.link_txn_id for r in imp.rows if r.link_txn_id and r.user_set}
    on_card = account is not None and account.type == AccountType.credit_card
    plans = plans_of(db, account.id) if on_card else []
    interest_days: dict = {}
    for row in imp.rows:
        if row.transaction_id:  # already imported
            continue
        if not row.user_set:
            _suggest(db, account, row, plans, interest_days)
            row.link_txn_id = None
        row.duplicate_of = None
        # a conversion already recorded when the EMI was added on the card page
        if on_card and row.emi_id and row.kind == "transfer" and row.amount > 0:
            plan = db.get(CardEmi, row.emi_id)
            made = db.get(Transaction, plan.created_txn_id) if plan and plan.created_txn_id else None
            if made is not None and made.amount == row.amount and made.id not in claimed:
                row.duplicate_of = made.id
                claimed.add(made.id)
                if not row.user_set:
                    row.include = False
                continue
        if account is not None:
            dup = find_duplicate(db, row, account.id, claimed)
            if dup:
                row.duplicate_of = dup
                claimed.add(dup)
        # card statement: "payment received" already on the bank side as an expense
        if (
            account is not None
            and account.type == AccountType.credit_card
            and not row.user_set
            and row.kind == "transfer"
            and row.amount > 0
            and row.duplicate_of is None
        ):
            t = find_bank_side_expense(db, row, claimed)
            if t:
                row.link_txn_id = t.id
                row.transfer_account_id = t.source_id
                row.suggestion, row.suggestion_kind = f"Already recorded as an expense on {t.date:%d %b}", "link"
                claimed.add(t.id)
        if not row.user_set:
            row.include = row.duplicate_of is None


def row_status(row: StatementRow) -> str:
    if row.transaction_id:
        return "imported"
    if not row.include:
        return "duplicate" if row.duplicate_of else "skipped"
    if row.kind == "transfer":
        if row.link_txn_id:
            return "link"
        return "ready" if row.transfer_account_id else "needs_account"
    if row.category_id or row.leave_uncategorised:
        return "ready"
    return "needs_category"


def category_exists(db: Session, cid: int | None) -> bool:
    return cid is None or db.get(Category, cid) is not None

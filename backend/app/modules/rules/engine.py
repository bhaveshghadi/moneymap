"""The rules engine: match a transaction (or a statement row / Inbox alert not saved yet)
against the rules and work out what they set.

Text matching ignores case and extra spaces. Amounts are paise. Ids refer to accounts,
categories, budgets and bills. A rule with no conditions never matches (safety).
"""

import re
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..accounts.models import Account, AccountType
from ..accounts.service import find_or_create_counterparty
from ..bills.models import Bill
from ..budgets.models import Budget
from ..categories.models import Category, Tag
from ..transactions.models import Transaction
from .models import Rule

# type -> kind of value (drives validation and the editor on the Rules page)
CONDITIONS: dict[str, str] = {
    "description_contains": "text",
    "description_starts": "text",
    "description_is": "text",
    "payee_contains": "text",  # who you paid / who paid you
    "amount_is": "amount",
    "amount_more": "amount",
    "amount_less": "amount",
    "type_is": "type",
    "account_is": "account",  # one of your own accounts, either side
    "no_category": "none",
    "has_tag": "text",
}
ACTIONS: dict[str, str] = {
    "set_category": "category",
    "set_budget": "budget",
    "set_bill": "bill",
    "add_tag": "text",
    "remove_tag": "text",
    "set_payee": "text",  # rename: "UPI/SWIGGY/swiggy@ybl/…" -> "Swiggy"
    "set_description": "text",
    "add_note": "text",
}
TYPES = {"withdrawal", "deposit", "transfer"}


def bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


# ---------------------------------------------------------------- checking a rule


def clean(db: Session, items: list[dict], vocab: dict[str, str], what: str) -> list[dict]:
    """Validate conditions / actions; values come back in their stored form."""
    out = []
    for it in items:
        typ = it.get("type")
        if typ not in vocab:
            raise bad(f"Unknown {what}: {typ}")
        kind, v = vocab[typ], it.get("value")
        if kind == "none":
            out.append({"type": typ})
            continue
        if kind == "text":
            v = str(v or "").strip()
            if not v:
                raise bad(f"Fill in the text for every {what}.")
            v = v[:255]
        elif kind == "amount":
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise bad("Amounts must be numbers.") from None
            if v < 0:
                raise bad("Amounts can't be negative.")
        elif kind == "type":
            if v not in TYPES:
                raise bad("Choose expense, income or transfer.")
        else:
            model = {"account": Account, "category": Category, "budget": Budget, "bill": Bill}[kind]
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise bad(f"Choose the {kind} for every {what}.") from None
            if db.get(model, v) is None:
                raise bad(f"That {kind} no longer exists.")
        out.append({"type": typ, "value": v})
    return out


# ---------------------------------------------------------------- matching


@dataclass
class Probe:
    """What the rules look at — from a transaction, a statement row or an Inbox alert."""

    type: str
    amount: int
    description: str
    payee: str
    account_ids: set[int]
    category_id: int | None = None
    tags: set[str] = field(default_factory=set)


def probe_of(t: Transaction) -> Probe:
    if t.type == "withdrawal":
        payee = t.destination.name
    elif t.type == "deposit":
        payee = t.source.name
    else:
        payee = f"{t.source.name} {t.destination.name}"
    return Probe(
        type=t.type,
        amount=t.amount,
        description=t.description or "",
        payee=payee,
        account_ids={t.source_id, t.destination_id},
        category_id=t.category_id,
        tags={tag.name.lower() for tag in t.tags},
    )


def condition_matches(p: Probe, c: dict) -> bool:
    typ, v = c["type"], c.get("value")
    desc, text = _norm(p.description), _norm(str(v) if v is not None else "")
    match typ:
        case "description_contains":
            return text in desc
        case "description_starts":
            return desc.startswith(text)
        case "description_is":
            return desc == text
        case "payee_contains":
            return text in _norm(p.payee)
        case "amount_is":
            return p.amount == int(v)
        case "amount_more":
            return p.amount > int(v)
        case "amount_less":
            return p.amount < int(v)
        case "type_is":
            return p.type == v
        case "account_is":
            return int(v) in p.account_ids
        case "no_category":
            return p.category_id is None
        case "has_tag":
            return text in p.tags
    return False


def matches(p: Probe, rule: Rule) -> bool:
    if not rule.conditions:
        return False
    hits = (condition_matches(p, c) for c in rule.conditions)
    return all(hits) if rule.match_all else any(hits)


@dataclass
class Plan:
    """What the matching rules set, in rule order (a later rule doesn't undo an earlier one)."""

    category_id: int | None = None
    budget_id: int | None = None
    bill_id: int | None = None
    add_tags: list[str] = field(default_factory=list)
    remove_tags: list[str] = field(default_factory=list)
    payee: str | None = None
    description: str | None = None
    notes: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)

    @property
    def title(self) -> str | None:
        return ", ".join(r.title for r in self.rules) if self.rules else None


def active_rules(db: Session) -> list[Rule]:
    return list(db.scalars(select(Rule).where(Rule.active.is_(True)).order_by(Rule.position, Rule.id)))


def plan_for(p: Probe, rules: list[Rule]) -> Plan:
    plan = Plan()
    for rule in rules:
        if not matches(p, rule):
            continue
        plan.rules.append(rule)
        for a in rule.actions:
            typ, v = a["type"], a.get("value")
            if typ == "set_category" and plan.category_id is None and p.type != "transfer":
                plan.category_id = int(v)
            elif typ == "set_budget" and plan.budget_id is None and p.type == "withdrawal":
                plan.budget_id = int(v)
            elif typ == "set_bill" and plan.bill_id is None and p.type == "withdrawal":
                plan.bill_id = int(v)
            elif typ == "add_tag" and str(v).lower() not in {t.lower() for t in plan.add_tags}:
                plan.add_tags.append(str(v))
            elif typ == "remove_tag":
                plan.remove_tags.append(str(v))
            elif typ == "set_payee" and plan.payee is None and p.type != "transfer":
                plan.payee = str(v)
            elif typ == "set_description" and plan.description is None:
                plan.description = str(v)
            elif typ == "add_note" and str(v) not in plan.notes:
                plan.notes.append(str(v))
        if rule.stop:
            break
    return plan


# ---------------------------------------------------------------- applying


def _tag(db: Session, name: str) -> Tag:
    tag = db.scalar(select(Tag).where(func.lower(Tag.name) == name.lower()))
    if tag is None:
        tag = Tag(name=name[:64])
        db.add(tag)
        db.flush()
    return tag


def apply_plan(db: Session, t: Transaction, plan: Plan, overwrite: bool, skip: set[str] = frozenset()) -> bool:
    """Put a plan on a saved transaction. `overwrite=False` only fills what's empty (and never
    renames the payee or description or removes tags). Returns True when something changed."""
    changed = False

    def put(attr: str, value) -> None:
        nonlocal changed
        if value is None or attr in skip or getattr(t, attr) == value:
            return
        if getattr(t, attr) is not None and not overwrite:
            return
        setattr(t, attr, value)
        changed = True

    cat = db.get(Category, plan.category_id) if plan.category_id else None
    wanted = {"withdrawal": "expense", "deposit": "income"}.get(t.type)
    put("category_id", cat.id if cat is not None and cat.kind == wanted else None)  # an expense category for an expense
    put("budget_id", plan.budget_id)
    put("bill_id", plan.bill_id)
    have = {tag.name.lower() for tag in t.tags}
    for name in plan.add_tags:
        if name.lower() not in have:
            t.tags = [*t.tags, _tag(db, name)]
            have.add(name.lower())
            changed = True
    if overwrite and plan.remove_tags:
        drop = {n.lower() for n in plan.remove_tags}
        keep = [tag for tag in t.tags if tag.name.lower() not in drop]
        if len(keep) != len(t.tags):
            t.tags, changed = keep, True
    if overwrite and plan.payee and "payee" not in skip and t.type in ("withdrawal", "deposit"):
        kind = AccountType.expense if t.type == "withdrawal" else AccountType.revenue
        other = find_or_create_counterparty(db, plan.payee, kind)
        attr = "destination_id" if t.type == "withdrawal" else "source_id"
        if getattr(t, attr) != other.id:
            setattr(t, attr, other.id)
            changed = True
    if overwrite and plan.description and "description" not in skip and t.description != plan.description:
        t.description, changed = plan.description[:255], True
    for note in plan.notes:
        if note not in (t.notes or ""):
            t.notes = f"{t.notes}\n{note}" if t.notes else note
            changed = True
    return changed


def run_on_new(db: Session, t: Transaction) -> Plan:
    """A transaction you just added (by hand or from the Inbox): rules fill only what you left empty."""
    plan = plan_for(probe_of(t), active_rules(db))
    if plan.rules:
        apply_plan(db, t, plan, overwrite=False)
    return plan

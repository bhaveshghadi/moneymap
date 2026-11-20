from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...db import get_db
from ..accounts.models import Account
from ..auth.security import current_user
from ..bills.models import Bill
from ..budgets.models import Budget
from ..categories.models import Category
from ..transactions.models import Transaction
from ..transactions.service import txn_out
from .engine import ACTIONS, CONDITIONS, Plan, Probe, _norm, apply_plan, clean, plan_for, probe_of
from .models import Rule
from .schemas import (
    ApplyIn,
    ApplyOut,
    Change,
    MoveIn,
    RuleIn,
    RuleOut,
    RulePatch,
    Suggestion,
    TestOut,
)

router = APIRouter(prefix="/rules", tags=["rules"], dependencies=[Depends(current_user)])

SCAN_LIMIT = 20_000  # transactions looked at by test / apply (newest first)


def _get(db: Session, rid: int) -> Rule:
    r = db.get(Rule, rid)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    return r


def _ordered(db: Session) -> list[Rule]:
    return list(db.scalars(select(Rule).order_by(Rule.position, Rule.id)))


def _renumber(rules: list[Rule]) -> None:
    for i, r in enumerate(rules):
        r.position = i


def describe(db: Session, t: Transaction, plan: Plan, overwrite: bool) -> list[str]:
    """What applying the plan would change on `t`, in words (nothing is saved)."""
    out = []

    def name(model, i):
        x = db.get(model, i) if i else None
        return x.name if x is not None else None

    wanted = {"withdrawal": "expense", "deposit": "income"}.get(t.type)
    cat = db.get(Category, plan.category_id) if plan.category_id else None
    if cat is not None and cat.kind == wanted and t.category_id != cat.id and (overwrite or t.category_id is None):
        out.append(f"Category: {cat.name}")
    if plan.budget_id and t.budget_id != plan.budget_id and (overwrite or t.budget_id is None):
        out.append(f"Budget: {name(Budget, plan.budget_id)}")
    if plan.bill_id and t.bill_id != plan.bill_id and (overwrite or t.bill_id is None):
        out.append(f"Bill: {name(Bill, plan.bill_id)}")
    have = {tag.name.lower() for tag in t.tags}
    out += [f"Tag: #{n}" for n in plan.add_tags if n.lower() not in have]
    if overwrite:
        out += [f"Remove tag: #{n}" for n in plan.remove_tags if n.lower() in have]
        current = probe_of(t).payee
        if plan.payee and t.type in ("withdrawal", "deposit") and _norm(current) != _norm(plan.payee):
            out.append(f"Payee: {plan.payee}")
        if plan.description and t.description != plan.description:
            out.append(f"Description: {plan.description}")
    out += [f"Note: {n}" for n in plan.notes if n not in (t.notes or "")]
    return out


def _scan(db: Session, since=None):
    q = select(Transaction).order_by(Transaction.date.desc(), Transaction.id.desc()).limit(SCAN_LIMIT)
    if since:
        q = q.where(Transaction.date >= since)
    return db.scalars(q).unique()


# ---------------------------------------------------------------- list / edit


@router.get("", response_model=list[RuleOut])
def list_rules(db: Session = Depends(get_db)) -> list[Rule]:
    return _ordered(db)


@router.get("/vocabulary")
def vocabulary() -> dict:
    return {"conditions": CONDITIONS, "actions": ACTIONS}


@router.post("", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, db: Session = Depends(get_db)) -> Rule:
    rule = Rule(
        title=body.title.strip(),
        active=body.active,
        match_all=body.match_all,
        stop=body.stop,
        conditions=clean(db, [c.model_dump() for c in body.conditions], CONDITIONS, "condition"),
        actions=clean(db, [a.model_dump() for a in body.actions], ACTIONS, "action"),
        position=(db.scalar(select(func.max(Rule.position))) or 0) + 1,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/{rid}", response_model=RuleOut)
def update_rule(rid: int, body: RulePatch, db: Session = Depends(get_db)) -> Rule:
    rule = _get(db, rid)
    data = body.model_dump(exclude_unset=True)
    for f in ("active", "match_all", "stop"):
        if data.get(f) is not None:
            setattr(rule, f, data[f])
    if data.get("title"):
        rule.title = data["title"].strip()
    if body.conditions is not None:
        rule.conditions = clean(db, [c.model_dump() for c in body.conditions], CONDITIONS, "condition")
    if body.actions is not None:
        rule.actions = clean(db, [a.model_dump() for a in body.actions], ACTIONS, "action")
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rid}", status_code=204)
def delete_rule(rid: int, db: Session = Depends(get_db)) -> None:
    db.delete(_get(db, rid))
    db.flush()
    _renumber(_ordered(db))
    db.commit()


@router.post("/{rid}/move", response_model=list[RuleOut])
def move_rule(rid: int, body: MoveIn, db: Session = Depends(get_db)) -> list[Rule]:
    rules = _ordered(db)
    i = next((n for n, r in enumerate(rules) if r.id == rid), None)
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    j = i - 1 if body.direction == "up" else i + 1
    if 0 <= j < len(rules):
        rules[i], rules[j] = rules[j], rules[i]
    _renumber(rules)
    db.commit()
    return rules


# ---------------------------------------------------------------- test / apply to existing


@router.post("/test", response_model=TestOut)
def test_rule(body: RuleIn, overwrite: bool = False, db: Session = Depends(get_db)) -> TestOut:
    """Which existing transactions a rule (saved or not) matches, and what it would change."""
    rule = Rule(
        title=body.title,
        match_all=body.match_all,
        stop=False,
        conditions=clean(db, [c.model_dump() for c in body.conditions], CONDITIONS, "condition"),
        actions=clean(db, [a.model_dump() for a in body.actions], ACTIONS, "action"),
    )
    matched = would = 0
    items: list[Change] = []
    for t in _scan(db):
        plan = plan_for(probe_of(t), [rule])
        if not plan.rules:
            continue
        matched += 1
        changes = describe(db, t, plan, overwrite)
        would += bool(changes)
        if len(items) < 50:
            items.append(Change(transaction=txn_out(t), changes=changes))
    return TestOut(matched=matched, would_change=would, items=items)


@router.post("/{rid}/apply", response_model=ApplyOut)
def apply_rule(rid: int, body: ApplyIn, db: Session = Depends(get_db)) -> ApplyOut:
    """Run one rule over existing transactions (its on/off switch doesn't matter here)."""
    rule = _get(db, rid)
    matched = changed = 0
    for t in _scan(db, body.since):
        plan = plan_for(probe_of(t), [rule])
        if not plan.rules:
            continue
        matched += 1
        changed += apply_plan(db, t, plan, overwrite=body.overwrite)
    db.commit()
    return ApplyOut(matched=matched, changed=changed)


# ---------------------------------------------------------------- suggested rules


@router.get("/suggestions", response_model=list[Suggestion])
def suggestions(db: Session = Depends(get_db)) -> list[Suggestion]:
    """Payees you've put in the same category at least 3 times (and 80% of the time), that
    no rule covers yet."""
    rules = [r for r in _ordered(db) if r.active]
    rows = db.execute(
        select(Transaction.type, Account.name, Transaction.category_id, func.count())
        .join(
            Account,
            ((Transaction.type == "withdrawal") & (Transaction.destination_id == Account.id))
            | ((Transaction.type == "deposit") & (Transaction.source_id == Account.id)),
        )
        .where(Transaction.type.in_(("withdrawal", "deposit")), Transaction.category_id.is_not(None))
        .group_by(Transaction.type, Account.name, Transaction.category_id)
    ).all()
    by_payee: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for typ, payee, cid, n in rows:
        by_payee.setdefault((typ, payee), []).append((cid, n))
    cats = {c.id: c.name for c in db.scalars(select(Category))}
    out = []
    for (typ, payee), counts in by_payee.items():
        cid, n = max(counts, key=lambda x: x[1])
        total = sum(c for _, c in counts)
        if n < 3 or n < 0.8 * total:
            continue
        probe = Probe(type=typ, amount=0, description=payee, payee=payee, account_ids=set())
        if plan_for(probe, rules).category_id is not None:
            continue  # a rule already sets this payee's category
        out.append(
            Suggestion(payee=payee, type=typ, category_id=cid, category=cats.get(cid, "?"), count=n, total=total)
        )
    return sorted(out, key=lambda s: -s.count)[:30]

"""Card summaries: balances and billing cycles from the card account's transactions."""

from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..accounts.models import Account
from ..statements.models import StatementImport
from ..transactions.models import Transaction
from .cycles import Cycle, Rule, build_cycles, due_date, next_statement, rule_at
from .emi import emi_out, plans_of
from .models import CardCycleRule, CreditCard
from .schemas import CardDetail, CardDue, CardOut, CycleOut

UNPAID = {"billed", "partly_paid", "overdue"}


def rules_of(card: CreditCard) -> list[Rule]:
    return [Rule(r.effective_from, r.statement_day, r.due_mode, r.due_value) for r in card.rules]


def _moves(db: Session, account_id: int) -> list[tuple[date, int]]:
    """(date, signed amount) of every transaction on the card: out negative, in positive."""
    rows = db.execute(
        select(Transaction.date, Transaction.amount, Transaction.destination_id).where(
            or_(Transaction.source_id == account_id, Transaction.destination_id == account_id)
        )
    ).all()
    return [(d, amt if dst == account_id else -amt) for d, amt, dst in rows]


def _cycle_out(c: Cycle) -> CycleOut:
    return CycleOut(**c.__dict__)


def card_cycles(db: Session, card: CreditCard, today: date | None = None) -> tuple[list[Cycle], list[tuple]]:
    today = today or date.today()
    moves = _moves(db, card.account_id)
    a = card.account
    since = a.opening_date or min([d for d, _ in moves] or [today])
    # transactions dated before the opening date still count, from their own cycle
    since = min([since, *[d for d, _ in moves]])
    opening_owed = max(0, -a.opening_balance)
    rules = rules_of(card)
    first = build_cycles(rules, opening_owed, since, moves, today, card.min_due_pct)
    official = official_figures(db, card, [c.statement_date for c in first if c.status != "unbilled"])
    if not official:
        return first, moves
    return build_cycles(rules, opening_owed, since, moves, today, card.min_due_pct, official), moves


def official_figures(
    db: Session, card: CreditCard, statement_dates: list[date]
) -> dict[date, tuple[int | None, int | None, date | None]]:
    """Imported statements of this card, keyed by the cycle they belong to (the bank's
    statement date may differ from the card's statement day by a few days)."""
    out: dict[date, tuple[int | None, int | None, date | None]] = {}
    if not statement_dates:
        return out
    imports = db.scalars(
        select(StatementImport)
        .where(
            StatementImport.account_id == card.account_id,
            StatementImport.status == "imported",
            StatementImport.statement_date.is_not(None),
        )
        .order_by(StatementImport.id)
    )
    for imp in imports:
        near = min(statement_dates, key=lambda d: abs((d - imp.statement_date).days))
        if abs((near - imp.statement_date).days) <= 3:
            out[near] = (imp.total_due, imp.min_due, imp.due_date)
    return out


def card_out(db: Session, card: CreditCard, today: date | None = None, detail: bool = False) -> CardOut:
    today = today or date.today()
    cycles, moves = card_cycles(db, card, today)
    a = card.account
    owed = max(0, -(a.opening_balance + sum(amt for _, amt in moves)))
    closed = [c for c in cycles if c.status != "unbilled"]
    last = closed[-1] if closed else None
    due_now = (last.total_due - last.paid) if last and last.status in UNPAID else 0
    # An older statement left unpaid past its due date makes the whole card overdue.
    overdue = [c for c in closed if c.status == "overdue"]
    due_status = "overdue" if overdue else (last.status if due_now > 0 and last else None)
    next_due = (overdue[0].due_date if overdue else last.due_date) if due_now > 0 and last else None
    emis = [emi_out(db, e, a.id, today) for e in plans_of(db, a.id)]
    emi_left = sum(e.outstanding for e in emis)
    rules = rules_of(card)
    # Spending from the day after the open cycle's statement lands on the following
    # statement — the longest wait before you have to pay.
    swipe = cycles[-1].statement_date + timedelta(days=1)
    swipe_sd = next_statement(rules, cycles[-1].statement_date)
    swipe_due = due_date(swipe_sd, rule_at(rules, swipe_sd))
    current = rules[-1]
    data = dict(
        id=a.id,
        name=a.name,
        bank=card.bank,
        last4=card.last4,
        network=card.network,
        color=card.color,
        credit_limit=card.credit_limit,
        min_due_pct=card.min_due_pct,
        statement_day=current.statement_day,
        due_mode=current.due_mode,
        due_value=current.due_value,
        opening_owed=max(0, -a.opening_balance),
        opening_date=a.opening_date,
        active=a.active,
        notes=a.notes,
        owed=owed,
        emi_outstanding=emi_left,
        emi_count=sum(1 for e in emis if e.status == "active"),
        # the bank holds back the EMI principal still to pay from the limit
        available=(card.credit_limit - owed - emi_left) if card.credit_limit else None,
        utilisation=round((owed + emi_left) * 100 / card.credit_limit, 1) if card.credit_limit else None,
        current=_cycle_out(cycles[-1]),
        last_statement=_cycle_out(last) if last else None,
        due_now=due_now,
        next_due_date=next_due,
        due_status=due_status,
        best_swipe_day=swipe,
        interest_free_days=(swipe_due - swipe).days,
        transaction_count=len(moves),
    )
    if detail:
        return CardDetail(**data, cycles=[_cycle_out(c) for c in reversed(cycles)][:25], emis=emis)
    return CardOut(**data)


def all_cards(db: Session, include_inactive: bool = True) -> list[CardOut]:
    q = select(CreditCard).join(Account, CreditCard.account_id == Account.id)
    if not include_inactive:
        q = q.where(Account.active.is_(True))
    cards = db.scalars(q.order_by(Account.active.desc(), func.lower(Account.name))).unique()
    return [card_out(db, c) for c in cards]


def card_dues(db: Session, days: int = 30) -> list[CardDue]:
    """Card statements still to pay: overdue, or due in the next `days` days, soonest first."""
    horizon = date.today() + timedelta(days=days)
    out = []
    for c in all_cards(db, include_inactive=False):
        if c.due_now > 0 and c.next_due_date and c.last_statement and c.next_due_date <= horizon:
            out.append(
                CardDue(
                    card_id=c.id,
                    name=c.name,
                    last4=c.last4,
                    due_date=c.next_due_date,
                    amount=c.due_now,
                    min_due=max(0, c.last_statement.min_due - c.last_statement.paid),
                    status=c.due_status or c.last_statement.status,
                )
            )
    return sorted(out, key=lambda x: (x.status != "overdue", x.due_date))


def add_rule(db: Session, card: CreditCard, statement_day: int, due_mode: str, due_value: int, today: date) -> None:
    """New cycle settings apply to statements after the last one already issued, so
    past cycles keep their dates. A rule that never applied yet is simply replaced."""
    rules = rules_of(card)
    cur = rules[-1]
    if (cur.statement_day, cur.due_mode, cur.due_value) == (statement_day, due_mode, due_value):
        return
    cycles, _ = card_cycles(db, card, today)
    closed = [c for c in cycles if c.status != "unbilled"]
    effective = (closed[-1].statement_date + timedelta(days=1)) if closed else card.rules[0].effective_from
    last = card.rules[-1]
    if last.effective_from >= effective:
        last.statement_day, last.due_mode, last.due_value = statement_day, due_mode, due_value
    else:
        card.rules.append(
            CardCycleRule(effective_from=effective, statement_day=statement_day, due_mode=due_mode, due_value=due_value)
        )
    db.flush()

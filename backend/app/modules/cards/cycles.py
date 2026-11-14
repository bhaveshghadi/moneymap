"""Billing-cycle maths (pure functions, no database).

A cycle runs from the day after one statement date to the next statement date. The
statement total is what you owe on the statement date; it is paid once the money that
came into the card after that date (payments and refunds, oldest first) reaches it.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from ...core.dates import add_months

MIN_DUE_FLOOR = 20_000  # ₹200 — the usual minimum, capped at the total


@dataclass(frozen=True)
class Rule:
    effective_from: date
    statement_day: int
    due_mode: str  # days_after | fixed_day
    due_value: int


@dataclass
class Cycle:
    start: date  # first day of the cycle
    statement_date: date  # last day of the cycle
    due_date: date
    spent: int = 0  # money out of the card during the cycle
    credits: int = 0  # refunds and payments into the card during the cycle
    total_due: int = 0  # owed on the statement date
    min_due: int = 0
    paid: int = 0  # paid towards total_due since the statement (capped at it)
    paid_on: date | None = None  # when total_due was fully paid
    status: str = "unbilled"  # unbilled | nothing_due | billed | partly_paid | paid | overdue
    min_paid: bool = False  # overdue, but at least the minimum was paid by the due date
    official: bool = False  # total / minimum / due date taken from the imported statement


def _clamp(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def rule_at(rules: list[Rule], d: date) -> Rule:
    """The rule in force on `d` (the first rule also covers anything before it)."""
    current = rules[0]
    for r in rules:
        if r.effective_from <= d:
            current = r
    return current


def due_date(statement: date, rule: Rule) -> date:
    if rule.due_mode == "days_after":
        return statement + timedelta(days=rule.due_value)
    # fixed day of the month: the first such day after the statement date
    same = _clamp(statement.year, statement.month, rule.due_value)
    if same > statement:
        return same
    nxt = add_months(statement.replace(day=1), 1)
    return _clamp(nxt.year, nxt.month, rule.due_value)


def statement_dates(rules: list[Rule], start: date, end: date) -> list[date]:
    """Statement dates in [start, end], each following the rule in force on that date."""
    out: set[date] = set()
    m = add_months(start.replace(day=1), -1)
    while m <= end:
        for r in rules:
            d = _clamp(m.year, m.month, r.statement_day)
            if start <= d <= end and rule_at(rules, d) == r:
                out.add(d)
        m = add_months(m, 1)
    return sorted(out)


def next_statement(rules: list[Rule], after: date) -> date:
    """The first statement date after `after`."""
    return statement_dates(rules, after + timedelta(days=1), after + timedelta(days=70))[0]


def min_due_for(total: int, pct: int) -> int:
    if total <= 0:
        return 0
    return min(total, max(round(total * pct / 100), MIN_DUE_FLOOR))


def build_cycles(
    rules: list[Rule],
    opening_owed: int,
    since: date,
    moves: list[tuple[date, int]],
    today: date,
    min_due_pct: int,
    official: dict[date, tuple[int | None, int | None, date | None]] | None = None,
) -> list[Cycle]:
    """Every cycle from the one containing `since` up to the open one, oldest first.

    `moves` are the card's transactions as (date, signed amount): negative = money out
    of the card (spends), positive = money in (payments, refunds). `opening_owed` is what
    was owed before `since`. `official` holds an imported statement's own figures
    (total due, minimum due, due date) by statement date; they replace the worked-out ones.
    """
    moves = sorted(moves)
    first_sd = next_statement(rules, since - timedelta(days=1))
    dates = statement_dates(rules, first_sd, today)
    open_sd = next_statement(rules, dates[-1] if dates else first_sd - timedelta(days=1))
    if not dates or open_sd != dates[-1]:
        dates.append(open_sd)
    dates = sorted(set(dates))

    def owed_on(d: date) -> int:
        bal = -opening_owed + sum(a for md, a in moves if md <= d)
        return max(0, -bal)

    cycles: list[Cycle] = []
    prev = statement_dates(rules, first_sd - timedelta(days=70), first_sd - timedelta(days=1))[-1]
    for sd in dates:
        start = prev + timedelta(days=1)
        c = Cycle(start=start, statement_date=sd, due_date=due_date(sd, rule_at(rules, sd)))
        for md, a in moves:
            if start <= md <= sd:
                if a < 0:
                    c.spent += -a
                else:
                    c.credits += a
        if sd > today:
            c.status = "unbilled"
        else:
            c.total_due = owed_on(sd)
            c.min_due = min_due_for(c.total_due, min_due_pct)
            if official and sd in official:
                total, minimum, due = official[sd]
                c.official = True
                if total is not None:
                    c.total_due = max(0, total)
                    c.min_due = min_due_for(c.total_due, min_due_pct)
                if minimum is not None:
                    c.min_due = min(max(0, minimum), c.total_due)
                if due is not None:
                    c.due_date = due
            if c.total_due == 0:
                c.status = "nothing_due"
            else:
                cum, cum_by_due = 0, 0
                for md, a in moves:
                    if md > sd and a > 0:
                        cum += a
                        if md <= c.due_date:
                            cum_by_due += a
                        if cum >= c.total_due and c.paid_on is None:
                            c.paid_on = md
                c.paid = min(cum, c.total_due)
                if c.paid >= c.total_due:
                    c.status = "paid"
                elif today <= c.due_date:
                    c.status = "partly_paid" if c.paid > 0 else "billed"
                else:
                    c.status = "overdue"
                    c.min_paid = cum_by_due >= c.min_due
        cycles.append(c)
        prev = sd
    return cycles

"""Savings plan: a month's income split into needs / wants / savings against a rule (50/30/20 …),
with suggestions from fixed rules. Nothing leaves the server.

Needs = spending in Essential categories + loan EMIs (an EMI expense, or the principal moved to a
loan). Wants = all other spending (uncategorised included). Spending in the "Investment" category
is money saved, not a want. Savings = income − needs − wants, split into moved to investments,
set aside in piggy banks / the emergency fund, and left in the bank.
"""

import json
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from ...core.dates import add_months, month_bounds
from ..accounts.models import BALANCE_TYPES, Account, AccountType
from ..auth.models import Setting
from ..budgets.models import Budget, BudgetCategory
from ..categories.models import Category
from ..emergency.service import compute as emergency_compute
from ..loans.service import monthly_emis
from ..piggybanks.models import PiggyEvent
from ..transactions.models import Transaction, TransactionType
from .schemas import (
    BudgetProposal,
    BudgetProposals,
    Line,
    SavingsPlanOut,
    SavingsSettings,
    SavingsSplit,
    Share,
    Suggestion,
)

KEY = "savings.plan"
RUPEE = 100
INVESTMENT_NAMES = {"investment", "investments", "sip", "mutual funds"}
EMI_WARN_PCT = 40
GREW = 1.2  # a category 20% above its 3-month average "grew"
LABEL = {"50_30_20": "50/30/20", "60_20_20": "60/20/20", "70_20_10": "70/20/10", "80_20": "80/20", "custom": "Custom"}


def bad(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


# ---------------------------------------------------------------- settings


def get_settings(db: Session) -> SavingsSettings:
    row = db.get(Setting, KEY)
    if row is not None:
        try:
            return SavingsSettings(**json.loads(row.value))
        except (ValueError, TypeError):
            pass
    return SavingsSettings()


def save_settings(db: Session, s: SavingsSettings) -> SavingsSettings:
    row = db.get(Setting, KEY) or Setting(key=KEY, value="")
    row.value = s.model_dump_json()
    db.add(row)
    db.commit()
    return s


# ---------------------------------------------------------------- one window


def _round100(paise: int) -> int:
    return round(paise / (100 * RUPEE)) * 100 * RUPEE


def investment_category_ids(db: Session) -> set[int]:
    return {
        c.id
        for c in db.scalars(select(Category).where(Category.kind == "expense"))
        if c.name.strip().lower() in INVESTMENT_NAMES
    }


class Window:
    """Totals for [start, end): income, spending by category (loan-linked apart), loan principal
    moved, money into / out of investments, piggy bank set-asides."""

    def __init__(self, db: Session, start: date, end: date):
        self.start, self.end = start, end
        in_w = and_(Transaction.date >= start, Transaction.date < end)
        self.income = int(
            db.scalar(
                select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                    in_w, Transaction.type == TransactionType.deposit.value
                )
            )
            or 0
        )
        # spending: (category, linked to a loan) -> amount
        self.by_cat: dict[int | None, int] = {}
        self.loan_emi = 0
        for cid, loan_id, amount in db.execute(
            select(Transaction.category_id, Transaction.loan_id, func.sum(Transaction.amount))
            .where(in_w, Transaction.type == TransactionType.withdrawal.value)
            .group_by(Transaction.category_id, Transaction.loan_id)
        ):
            if loan_id is not None:
                self.loan_emi += int(amount)
            else:
                self.by_cat[cid] = self.by_cat.get(cid, 0) + int(amount)
        src, dst = aliased(Account), aliased(Account)
        balance = [str(t) for t in BALANCE_TYPES]

        def moved(from_types: list[str], to_type: str) -> int:
            return int(
                db.scalar(
                    select(func.coalesce(func.sum(Transaction.amount), 0))
                    .join(src, Transaction.source_id == src.id)
                    .join(dst, Transaction.destination_id == dst.id)
                    .where(
                        in_w,
                        Transaction.type == TransactionType.transfer.value,
                        src.type.in_(from_types),
                        dst.type == to_type,
                    )
                )
                or 0
            )

        self.loan_principal = moved(balance, AccountType.loan.value)  # loans counted as principal + interest
        invest_in = moved(balance, AccountType.investment.value)
        invest_out = int(
            db.scalar(
                select(func.coalesce(func.sum(Transaction.amount), 0))
                .join(src, Transaction.source_id == src.id)
                .join(dst, Transaction.destination_id == dst.id)
                .where(
                    in_w,
                    Transaction.type == TransactionType.transfer.value,
                    src.type == AccountType.investment.value,
                    dst.type.in_(balance),
                )
            )
            or 0
        )
        self.invest_net = invest_in - invest_out
        self.to_goals = int(
            db.scalar(
                select(func.coalesce(func.sum(PiggyEvent.amount), 0)).where(
                    PiggyEvent.date >= start, PiggyEvent.date < end
                )
            )
            or 0
        )


def _period(month: str | None, today: date) -> tuple[str, str, date, date, int]:
    """("YYYY-MM" | "avg3", label, start, end, months)."""
    if month == "avg3":
        end = today.replace(day=1)
        start = add_months(end, -3, 1)
        return "avg3", f"{start:%b} – {add_months(end, -1, 1):%b %Y} average", start, end, 3
    try:
        start, end, label = month_bounds(month, today)
    except ValueError:
        raise bad("month must look like YYYY-MM, or avg3") from None
    return label, f"{start:%B %Y}", start, end, 1


def _share(amount: int, income: int, target_pct: int | None) -> Share:
    target = round(income * target_pct / 100) if target_pct is not None and income > 0 else None
    return Share(
        amount=amount,
        pct=round(amount * 100 / income, 1) if income > 0 else None,
        target_pct=target_pct,
        target=target,
        diff=(amount - target) if target is not None else None,
    )


def compute(db: Session, month: str | None = None, today: date | None = None) -> SavingsPlanOut:
    today = today or date.today()
    s = get_settings(db)
    period, label, start, end, months = _period(month, today)
    w = Window(db, start, end)
    per = lambda x: round(x / months)  # noqa: E731  (the average month for avg3)

    # the income the shares are of
    income = per(w.income)
    if s.basis == "fixed":
        income_used = s.fixed_income or 0
    elif s.basis == "avg3" and months == 1:
        # the viewed month and the 2 before it; for this month (not over yet) the 3 complete months before
        this_month = today.replace(day=1)
        a_end = add_months(start, 1, 1) if start < this_month else this_month
        a_start = add_months(a_end, -3, 1)
        income_used = round(Window(db, a_start, a_end).income / 3)
    else:
        income_used = income

    cats = {c.id: c for c in db.scalars(select(Category))}
    invest_ids = investment_category_ids(db)

    # the 3 months before: to say which categories grew
    before = Window(db, add_months(start, -3, 1), start)

    def line(cid: int | None, amount: int) -> Line:
        c = cats.get(cid) if cid is not None else None
        return Line(
            category_id=cid,
            name=c.name if c else "Uncategorised",
            icon=c.icon if c else "circle-help",
            color=c.color if c else "slate",
            amount=per(amount),
            before=round(before.by_cat.get(cid, 0) / 3),
        )

    needs_lines: list[Line] = []
    wants_lines: list[Line] = []
    invest_spend = 0
    for cid, amount in w.by_cat.items():
        c = cats.get(cid) if cid is not None else None
        if cid in invest_ids:
            invest_spend += amount
        elif c is not None and c.essential:
            needs_lines.append(line(cid, amount))
        else:
            wants_lines.append(line(cid, amount))
    loans = w.loan_emi + w.loan_principal
    if loans:
        needs_lines.append(
            Line(category_id=None, name="Loan EMIs", icon="hand-coins", color="coral", amount=per(loans))
        )
    needs_lines.sort(key=lambda x: -x.amount)
    wants_lines.sort(key=lambda x: -x.amount)

    needs = sum(x.amount for x in needs_lines)
    wants = sum(x.amount for x in wants_lines)
    uncategorised = next((x.amount for x in wants_lines if x.category_id is None), 0)
    saved = income_used - needs - wants
    to_inv = per(w.invest_net + invest_spend)
    to_goals = per(w.to_goals)
    split = SavingsSplit(to_investments=to_inv, to_goals=to_goals, left_in_bank=saved - to_inv - to_goals)

    combined = s.needs is None
    out = SavingsPlanOut(
        settings=s,
        period=period,
        period_label=label,
        months=months,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        income=income,
        income_used=income_used,
        needs=_share(needs, income_used, s.needs),
        wants=_share(wants, income_used, s.wants),
        spending=_share(needs + wants, income_used, 100 - s.savings),
        savings=_share(saved, income_used, s.savings),
        savings_split=split,
        needs_lines=needs_lines,
        wants_lines=wants_lines,
        uncategorised=uncategorised,
        emi_monthly=monthly_emis(db),
        suggestions=[],
    )
    out.suggestions = suggest(db, out, combined)
    return out


# ---------------------------------------------------------------- suggestions


def _trim(lines: list[Line], over: int) -> list[Line]:
    """The 3 biggest lines and how much to cut each (in proportion), at least ₹100 steps."""
    top = [x for x in lines if x.amount > 0][:3]
    total = sum(x.amount for x in top)
    out = []
    for x in top:
        cut = max(100 * RUPEE, _round100(over * x.amount // total)) if total else 0
        out.append(x.model_copy(update={"amount": min(cut, x.amount)}))
    return out


def suggest(db: Session, p: SavingsPlanOut, combined: bool) -> list[Suggestion]:
    """Fixed rules, in order of importance. Amounts go in `amount` / `items` (the page masks them);
    titles say what to do without the figures."""
    out: list[Suggestion] = []
    if p.income_used <= 0:
        return [
            Suggestion(
                kind="no_income",
                tone="info",
                title="No income in this period",
                detail="Choose the 3-month average or a fixed take-home pay as the income, so the "
                "shares can be worked out.",
            )
        ]
    if combined:
        if (p.spending.diff or 0) > 0:
            out.append(
                Suggestion(
                    kind="spending_over",
                    tone="warn",
                    title="Spending is above its share",
                    detail="Trim the biggest categories:",
                    amount=p.spending.diff,
                    items=_trim(sorted(p.wants_lines + p.needs_lines, key=lambda x: -x.amount), p.spending.diff or 0),
                )
            )
    else:
        if (p.wants.diff or 0) > 0:
            grew = [x.name for x in p.wants_lines[:5] if x.before and x.amount > x.before * GREW]
            out.append(
                Suggestion(
                    kind="wants_over",
                    tone="warn",
                    title="Wants are above their share",
                    detail="Cut these by about the amounts shown"
                    + (f" — {', '.join(grew)} went up compared with the 3 months before." if grew else "."),
                    amount=p.wants.diff,
                    items=_trim(p.wants_lines, p.wants.diff or 0),
                )
            )
        if (p.needs.diff or 0) > 0:
            out.append(
                Suggestion(
                    kind="needs_over",
                    tone="warn",
                    title="Needs are above their share",
                    detail="Your biggest essential costs — worth checking plans, rent, bills or a cheaper option:",
                    amount=p.needs.diff,
                    items=[x.model_copy() for x in p.needs_lines[:3]],
                )
            )
    if p.emi_monthly and p.emi_monthly * 100 > p.income_used * EMI_WARN_PCT:
        out.append(
            Suggestion(
                kind="emi_high",
                tone="warn",
                title=f"Loan EMIs take more than {EMI_WARN_PCT}% of your income",
                detail="Banks treat this as stretched. Avoid new loans; part-payments on the costliest "
                "loan bring it down.",
                amount=p.emi_monthly,
            )
        )
    gap = -(p.savings.diff or 0)
    if gap > 0:
        e = emergency_compute(db)
        if e.configured and e.status in ("low", "building", "no_data"):
            out.append(
                Suggestion(
                    kind="emergency_first",
                    tone="info",
                    title="Build the emergency fund first",
                    detail="Until it covers your months of essentials, put savings there before investing.",
                    amount=min(gap, e.monthly_to_save) if e.monthly_to_save else gap,
                )
            )
        out.append(
            Suggestion(
                kind="save_more",
                tone="warn",
                title="Save more to reach your savings share",
                detail="Set this aside each month as income arrives — a SIP or a recurring deposit makes it automatic.",
                amount=_round100(gap) or gap,
            )
        )
    elif p.savings.target is not None:
        extra = p.savings_split.left_in_bank
        if extra > 1000 * RUPEE and p.savings.amount > p.savings.target:
            out.append(
                Suggestion(
                    kind="invest_extra",
                    tone="good",
                    title="You're ahead of your savings share",
                    detail="Money left in the bank earns little — move some into an investment or a goal.",
                    amount=_round100(extra),
                )
            )
    if p.uncategorised > 0:
        out.append(
            Suggestion(
                kind="uncategorised",
                tone="info",
                title="Some spending has no category",
                detail="It counts as wants until you categorise it — if some of it is essential, needs "
                "and wants change.",
                amount=p.uncategorised,
            )
        )
    if not any(x.tone == "warn" for x in out):
        out.insert(
            0,
            Suggestion(kind="on_track", tone="good", title=f"On track with {LABEL[p.settings.rule]}", detail=""),
        )
    return out


# ---------------------------------------------------------------- budgets from the rule


def budget_proposals(db: Session, today: date | None = None) -> BudgetProposals:
    """A monthly budget for each want category, scaled so they add up to the wants share."""
    today = today or date.today()
    s = get_settings(db)
    if s.wants is None:
        raise bad("This rule doesn't give wants a share of their own — pick 50/30/20, 60/20/20, 70/20/10 or Custom.")
    plan = compute(db, "avg3", today)
    target = round(plan.income_used * s.wants / 100) if plan.income_used > 0 else 0
    owner = {
        bc.category_id: b.name
        for bc, b in db.execute(select(BudgetCategory, Budget).join(Budget, Budget.id == BudgetCategory.budget_id))
    }
    items, taken = [], []
    for x in plan.wants_lines:
        if x.category_id is None or x.amount <= 0:
            continue
        p = BudgetProposal(
            category_id=x.category_id, name=x.name, icon=x.icon, color=x.color, average=x.amount, amount=0,
            budget_name=owner.get(x.category_id),
        )  # fmt: skip
        (taken if p.budget_name else items).append(p)
    total = sum(p.average for p in items)
    room = target - sum(p.average for p in taken)  # budgets you have use part of the share
    for p in items:
        p.amount = max(100 * RUPEE, _round100(p.average * max(room, 0) // total)) if total and room > 0 else 0
    return BudgetProposals(wants_target=target, total_average=total, items=items, taken=taken)

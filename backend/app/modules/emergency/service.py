"""Emergency fund maths: a typical month of essential spending × months of cover."""

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...core.dates import add_months
from ..categories.models import Category
from ..piggybanks.models import PiggyBank
from ..piggybanks.router import monthly_needed, piggy_out, saved_map
from ..transactions.models import Transaction, TransactionType
from .models import EmergencyFund
from .schemas import (
    EmergencyCategory,
    EmergencyEstimate,
    EmergencyMonth,
    EmergencyOneOff,
    EmergencyOut,
    EmergencyStatus,
    EmergencySummary,
)

MIN_MONTHS_FOR_MEDIAN = 3  # with fewer complete months the amount is shown as an estimate
AVERAGE_CHOICES = (3, 6, 12)
ONE_OFF_SHARE = 20  # % of a month's essential spending one payment must reach to be flagged
ONE_OFF_SIMILAR = 0.2  # a payment within +-20% in the same category in another month = it recurs
ONE_OFF_LOOKBACK = 12  # months searched (each way) for that recurring payment
MAX_ONE_OFFS = 5


def get_config(db: Session) -> EmergencyFund | None:
    return db.scalar(select(EmergencyFund).order_by(EmergencyFund.id).limit(1))


def median(values: list[int]) -> int:
    """Median of whole paise; the mean of the two middle values (rounded) for an even count."""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0
    mid = n // 2
    return s[mid] if n % 2 else round((s[mid - 1] + s[mid]) / 2)


def essential_history(db: Session, average_months: int, today: date | None = None) -> list[EmergencyMonth]:
    """Essential spending in each of the last `average_months` complete months (the
    current month is left out), starting no earlier than the month of the first transaction."""
    today = today or date.today()
    this_month = today.replace(day=1)
    first_txn = db.scalar(select(func.min(Transaction.date)))
    if first_txn is None:
        return []
    start = max(add_months(this_month, -average_months), first_txn.replace(day=1))
    if start >= this_month:
        return []
    ym = func.strftime("%Y-%m", Transaction.date)
    sums = dict(
        db.execute(
            select(ym, func.sum(Transaction.amount))
            .join(Category, Transaction.category_id == Category.id)
            .where(
                Transaction.type == TransactionType.withdrawal.value,
                Category.essential.is_(True),
                Transaction.date >= start,
                Transaction.date < this_month,
            )
            .group_by(ym)
        ).all()
    )
    out = []
    m = start
    while m < this_month:
        label = m.strftime("%Y-%m")
        out.append(EmergencyMonth(month=label, amount=int(sums.get(label) or 0)))
        m = add_months(m, 1, 1)
    return out


def _window(history: list[EmergencyMonth]) -> tuple[date, date] | None:
    """[first day of the oldest month, first day after the newest month) of a history run."""
    if not history:
        return None
    start = date.fromisoformat(history[0].month + "-01")
    return start, add_months(date.fromisoformat(history[-1].month + "-01"), 1, 1)


def breakdown(db: Session, history: list[EmergencyMonth]) -> list[EmergencyCategory]:
    """Each essential category's spending over the months in `history`, biggest first."""
    w = _window(history)
    if w is None:
        return []
    rows = db.execute(
        select(Category, func.sum(Transaction.amount))
        .join(Transaction, Transaction.category_id == Category.id)
        .where(
            Transaction.type == TransactionType.withdrawal.value,
            Category.essential.is_(True),
            Transaction.date >= w[0],
            Transaction.date < w[1],
        )
        .group_by(Category.id)
    ).all()
    grand = sum(int(t or 0) for _, t in rows)
    out = [
        EmergencyCategory(
            category_id=c.id,
            name=c.name,
            icon=c.icon,
            color=c.color,
            total=int(t),
            per_month=round(int(t) / len(history)),
            share=round(int(t) * 100 / grand, 1) if grand else 0.0,
        )
        for c, t in rows
        if t
    ]
    return sorted(out, key=lambda x: (-x.total, x.name.lower()))


def one_offs(db: Session, history: list[EmergencyMonth]) -> list[EmergencyOneOff]:
    """Single essential payments that make up a big part of their month (>= ONE_OFF_SHARE %)
    with no similar payment in the same category in another month - e.g. a land purchase
    filed under Housing, or a loan prepayment under Loan / EMI. Rent and EMIs that repeat
    every month are not flagged once there is more than one month of data."""
    w = _window(history)
    if w is None:
        return []
    month_total = {h.month: h.amount for h in history}
    candidates = db.execute(
        select(Transaction, Category)
        .join(Category, Transaction.category_id == Category.id)
        .where(
            Transaction.type == TransactionType.withdrawal.value,
            Category.essential.is_(True),
            Transaction.date >= w[0],
            Transaction.date < w[1],
        )
    ).all()
    out = []
    for t, c in candidates:
        total = month_total.get(t.date.strftime("%Y-%m")) or 0
        if total <= 0 or t.amount * 100 < total * ONE_OFF_SHARE:
            continue
        lo, hi = int(t.amount * (1 - ONE_OFF_SIMILAR)), int(t.amount * (1 + ONE_OFF_SIMILAR))
        month = t.date.replace(day=1)
        recurs = db.scalar(
            select(func.count(Transaction.id)).where(
                Transaction.type == TransactionType.withdrawal.value,
                Transaction.category_id == c.id,
                Transaction.amount.between(lo, hi),
                Transaction.date >= add_months(month, -ONE_OFF_LOOKBACK),
                Transaction.date < add_months(month, ONE_OFF_LOOKBACK + 1),
                or_(Transaction.date < month, Transaction.date >= add_months(month, 1, 1)),
            )
        )
        if recurs:
            continue
        out.append(
            EmergencyOneOff(
                transaction_id=t.id,
                date=t.date.isoformat(),
                description=t.description,
                category=c.name,
                amount=t.amount,
                share=round(t.amount * 100 / total, 1),
            )
        )
    out.sort(key=lambda x: (-x.amount, x.date))
    return out[:MAX_ONE_OFFS]


def typical_month(history: list[EmergencyMonth]) -> tuple[int, str]:
    """(amount, source) for a run of months: the median, marked as an estimate below 3 months."""
    if not history:
        return 0, "none"
    return median([h.amount for h in history]), "median" if len(history) >= MIN_MONTHS_FOR_MEDIAN else "estimate"


def estimates(db: Session, today: date | None = None) -> list[EmergencyEstimate]:
    out = []
    for n in AVERAGE_CHOICES:
        h = essential_history(db, n, today)
        amount, source = typical_month(h)
        out.append(EmergencyEstimate(average_months=n, monthly=amount, source=source, months_of_data=len(h)))
    return out


def status_for(monthly: int, saved: int, target: int) -> EmergencyStatus:
    if monthly <= 0:
        return "no_data"
    if saved >= target:
        return "done"
    covered = saved / monthly
    if covered >= 3:
        return "safe"
    return "building" if covered >= 1 else "low"


def compute(db: Session, today: date | None = None) -> EmergencyOut:
    """Everything the Emergency fund card shows. Keeps the piggy bank's target in
    step with the calculated target (the caller commits)."""
    cfg = get_config(db)
    piggy = db.get(PiggyBank, cfg.piggy_id) if cfg and cfg.piggy_id else None
    essentials = list(
        db.scalars(
            select(Category.name)
            .where(Category.essential.is_(True), Category.kind == "expense")
            .order_by(func.lower(Category.name))
        )
    )
    if cfg is None or piggy is None:
        return EmergencyOut(configured=False, essential_categories=essentials, estimates=estimates(db, today))

    history = essential_history(db, cfg.average_months, today)
    if cfg.monthly_override is not None:
        monthly, source = cfg.monthly_override, "override"
    else:
        monthly, source = typical_month(history)
    target = monthly * cfg.months_cover

    if piggy.target_amount != target:
        piggy.target_amount = target
        db.flush()
    saved_by_piggy = saved_map(db)
    p_out = piggy_out(db, piggy, saved_by_piggy)
    saved = p_out.saved
    return EmergencyOut(
        configured=True,
        piggy=p_out,
        months_cover=cfg.months_cover,
        average_months=cfg.average_months,
        monthly_override=cfg.monthly_override,
        monthly_essential=monthly,
        monthly_source=source,
        months_of_data=len(history),
        history=history,
        essential_categories=essentials,
        breakdown=breakdown(db, history),
        one_offs=one_offs(db, history),
        estimates=estimates(db, today),
        target=target,
        saved=saved,
        covered_months=round(saved / monthly, 1) if monthly > 0 else None,
        status=status_for(monthly, saved, target),
        monthly_to_save=monthly_needed(target, saved, piggy.target_date, today) if target > 0 else None,
    )


def summary(db: Session) -> EmergencySummary | None:
    """For the Overview; None until the fund is set up."""
    e = compute(db)
    if not e.configured:
        return None
    return EmergencySummary(
        target=e.target,
        saved=e.saved,
        months_cover=e.months_cover,
        covered_months=e.covered_months,
        status=e.status,
    )

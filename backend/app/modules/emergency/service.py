"""Emergency fund maths: a typical month of essential spending × months of cover."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.dates import add_months
from ..categories.models import Category
from ..piggybanks.models import PiggyBank
from ..piggybanks.router import monthly_needed, piggy_out, saved_map
from ..transactions.models import Transaction, TransactionType
from .models import EmergencyFund
from .schemas import EmergencyEstimate, EmergencyMonth, EmergencyOut, EmergencyStatus, EmergencySummary

MIN_MONTHS_FOR_MEDIAN = 3  # with fewer complete months the amount is shown as an estimate
AVERAGE_CHOICES = (3, 6, 12)


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

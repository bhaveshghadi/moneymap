"""Bill schedules and status (pure functions, no database)."""

from dataclasses import dataclass
from datetime import date, timedelta

from ...core.dates import add_months
from .models import Bill, BillRepeat

_MONTHS = {
    BillRepeat.monthly: 1,
    BillRepeat.quarterly: 3,
    BillRepeat.half_yearly: 6,
    BillRepeat.yearly: 12,
}


def nth_due(bill: Bill, k: int) -> date:
    """k-th due date (k=0 is first_due). Month-based schedules keep the first
    due date's day, clamped to the month's length (31 Jan → 28 Feb → 31 Mar)."""
    step = bill.skip + 1
    if bill.repeat == BillRepeat.weekly:
        return bill.first_due + timedelta(weeks=k * step)
    return add_months(bill.first_due, k * step * _MONTHS[BillRepeat(bill.repeat)], bill.first_due.day)


def due_index_on_or_before(bill: Bill, d: date) -> int:
    """Largest k with nth_due(k) <= d, or -1 if d is before the first due date."""
    if d < bill.first_due:
        return -1
    if bill.repeat == BillRepeat.weekly:
        return (d - bill.first_due).days // (7 * (bill.skip + 1))
    months = (d.year - bill.first_due.year) * 12 + d.month - bill.first_due.month
    k = max(0, months // (_MONTHS[BillRepeat(bill.repeat)] * (bill.skip + 1)) - 1)
    while nth_due(bill, k + 1) <= d:
        k += 1
    while k >= 0 and nth_due(bill, k) > d:
        k -= 1
    return k


def period_days(bill: Bill) -> int:
    if bill.repeat == BillRepeat.weekly:
        return 7 * (bill.skip + 1)
    return 30 * _MONTHS[BillRepeat(bill.repeat)] * (bill.skip + 1)


def late_days(bill: Bill) -> int:
    """A payment up to this many days after a due date still counts for it (7 days,
    or a quarter of the period for short schedules like weekly)."""
    return min(7, period_days(bill) // 4)


def payment_window(bill: Bill, k: int) -> tuple[date, date]:
    """Payments in (start, end] count for the k-th due date: from just after the
    previous due date's late days up to this due date's late days. The windows
    follow each other without gaps, so every payment belongs to exactly one due date —
    the one it is nearest to (paying early or a few days late both count)."""
    late = timedelta(days=late_days(bill))
    prev = nth_due(bill, k - 1) if k > 0 else bill.first_due - timedelta(days=period_days(bill))
    return prev + late, nth_due(bill, k) + late


def monthly_cost(bill: Bill) -> int:
    """The average amount, spread over a month (paise)."""
    avg = (bill.amount_min + bill.amount_max) // 2
    if bill.repeat == BillRepeat.weekly:
        return round(avg * 52 / 12 / (bill.skip + 1))
    return round(avg / (_MONTHS[BillRepeat(bill.repeat)] * (bill.skip + 1)))


@dataclass
class BillState:
    next_due: date | None
    status: str  # paid | due_soon | overdue | upcoming | inactive
    prev_due: date | None


def bill_state(bill: Bill, paid_dates: list[date], today: date | None = None) -> BillState:
    """Where a bill stands today, given the dates of the payments linked to it."""
    today = today or date.today()

    def paid(k: int) -> bool:
        start, end = payment_window(bill, k)
        return any(start < p <= end for p in paid_dates)

    k = due_index_on_or_before(bill, today)
    next_k = k + 1
    next_due = nth_due(bill, next_k)
    prev_due = nth_due(bill, k) if k >= 0 else None
    if not bill.active:
        return BillState(next_due, "inactive", prev_due)

    created = bill.created_at.date() if bill.created_at else today
    # An unpaid due date that has passed comes first, even if the next one is paid already.
    if k >= 0 and prev_due is not None and not paid(k):
        if prev_due == today:
            return BillState(today, "due_soon", prev_due)
        # Only due dates after the bill was added can be overdue — earlier ones
        # were probably paid before you started tracking.
        if prev_due >= created:
            return BillState(prev_due, "overdue", prev_due)
    if paid(next_k):  # the next one is already paid early
        return BillState(nth_due(bill, next_k + 1), "paid", next_due)
    # Within a week of the next due date it's "due soon", whether or not the last one was paid.
    if (next_due - today).days <= 7:
        return BillState(next_due, "due_soon", prev_due)
    return BillState(next_due, "paid" if k >= 0 and paid(k) else "upcoming", prev_due)

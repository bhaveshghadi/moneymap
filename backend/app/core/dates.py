import calendar
from datetime import date


def add_months(d: date, n: int, day: int | None = None) -> date:
    """Shift by n months, keeping `day` (default d.day) clamped to month length."""
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(day or d.day, calendar.monthrange(y, m)[1]))


def month_bounds(month: str | None, today: date | None = None) -> tuple[date, date, str]:
    """'YYYY-MM' -> (first day, first day of next month, 'YYYY-MM'). Defaults to this month.
    Raises ValueError for a malformed month."""
    today = today or date.today()
    if month:
        y_s, m_s = month.split("-", 1)
        y, m = int(y_s), int(m_s)
        if not (1 <= m <= 12 and 1900 <= y <= 9999):
            raise ValueError("bad month")
    else:
        y, m = today.year, today.month
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start, end, f"{y:04d}-{m:02d}"

"""Loan maths: EMI, repayment schedule (reducing balance, flat rate, EMI only).

Ported from the earlier build (moneymap_old/backend/app/loans.py), with its test
vectors. All money is integer paise; the rate is in hundredths of a percent (bp).

- reducing: as Indian banks run home / car / personal loans. Interest each month is
  the outstanding balance × yearly rate / 12; the EMI covers that month's interest and
  the rest repays principal; the last EMI is adjusted to clear the balance.
- flat: interest is worked out once on the full amount for the whole term
  (amount × rate × years) and spread evenly over the EMIs (some consumer,
  two-wheeler and gold loans).
- first EMI: lenders often charge EMI 1 the interest for the actual days from the loan being
  paid out to the first EMI ("broken period"), on a 365- or 360-day year, instead of one
  month's interest (`first_interest` = days365 | days360 | month). The EMI is set so the
  loan still ends on time.
- emi_only: you know the EMI and the number of months. With the amount too, the
  yearly rate is worked out from them and the schedule is reducing; without it, the
  "balance" is simply what's left to pay (EMIs × months) and there's no split.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from ...core.dates import add_months

MAX_MONTHS = 600  # 50 years — guards against an EMI that never repays


@dataclass
class Row:
    n: int  # 1-based EMI number
    date: date
    emi: int
    principal: int
    interest: int
    balance: int  # left after this EMI


def month_interest(balance: int, rate_bp: int) -> int:
    """balance × rate/12, rounded half up to the paisa (rate_bp/100 % a year)."""
    return (balance * rate_bp + 60_000) // 120_000


INTEREST_BASIS = ("month", "days365")


def period_interest(balance: int, rate_bp: int, due: date, daily: bool) -> int:
    """The interest charged with the EMI due on `due`: a month's (rate/12), or — `daily`, as some
    lenders (e.g. Bandhan) do — the actual days since the previous due date on a 365-day year,
    so February costs less than March. Rounded half up to the paisa."""
    if not daily:
        return month_interest(balance, rate_bp)
    days = (due - add_months(due, -1)).days
    return (balance * rate_bp * days + 1_825_000) // 3_650_000  # x rate/100/100 x days/365


def round_rupee(paise: Decimal | int) -> int:
    return int((Decimal(paise) / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * 100


FIRST_INTEREST = ("month", "days365", "days360")


def first_emi_interest(
    principal: int | None, rate_bp: int | None, first: date, taken_on: date | None, mode: str
) -> int | None:
    """Interest in EMI 1 counted by days: amount × rate × days from `taken_on` (the loan paid
    out) to the first EMI / 365 or 360, rounded half up to the paisa. None = one normal month."""
    if mode not in ("days365", "days360") or not taken_on or not principal or rate_bp is None or taken_on >= first:
        return None
    den = 10_000 * (365 if mode == "days365" else 360)
    return (principal * rate_bp * (first - taken_on).days + den // 2) // den


def calc_emi(principal: int, rate_bp: int, months: int, first_interest: int | None = None) -> int:
    """Standard EMI formula, rounded to the nearest rupee. With `first_interest` (EMI 1 carries
    that interest instead of a month's), the EMI that still clears the loan in `months`:
    after EMI 1 the balance is P + first_interest − EMI, repaid by months − 1 more EMIs."""
    if months <= 0 or principal <= 0:
        return 0
    if rate_bp == 0:
        return round_rupee(Decimal(principal) / months)
    r = Decimal(rate_bp) / Decimal(120_000)
    if first_interest is not None and months > 1:
        annuity = (1 - (1 + r) ** -(months - 1)) / r  # value today of 1 a month for months − 1 months
        return round_rupee((Decimal(principal) + first_interest) / (1 + annuity))
    f = (1 + r) ** months
    return round_rupee(Decimal(principal) * r * f / (f - 1))


def flat_emi(principal: int, rate_bp: int, months: int) -> int:
    """Flat rate: (amount + amount × rate × years) / months, rounded to the rupee."""
    if months <= 0 or principal <= 0:
        return 0
    interest = Decimal(principal) * rate_bp * months / Decimal(120_000)
    return round_rupee((principal + interest) / months)


def build(
    balance: int,
    rate_bp: int,
    emi: int,
    months: int,
    anchor: date,
    start_n: int = 1,
    first_interest: int | None = None,
    daily: bool = False,
) -> list[Row]:
    """Reducing-balance schedule from `balance`, paying `emi` monthly for at most `months`
    EMIs; the last one clears whatever is left. Dates are anchor + (n-1) months.
    `first_interest` replaces the month's interest of EMI 1 (see first_emi_interest);
    `daily` charges each month's interest on its actual days (see period_interest)."""
    rows: list[Row] = []
    n = start_n
    while balance > 0 and len(rows) < min(months, MAX_MONTHS):
        due = add_months(anchor, n - 1)
        interest = (
            first_interest if n == 1 and first_interest is not None else period_interest(balance, rate_bp, due, daily)
        )
        last = len(rows) == months - 1
        principal = emi - interest
        if principal <= 0 and not last:
            raise ValueError("The EMI doesn't even cover the monthly interest — check the EMI and interest rate.")
        if last or principal >= balance:
            principal = balance
        balance -= principal
        rows.append(Row(n, add_months(anchor, n - 1), principal + interest, principal, interest, balance))
        n += 1
    return rows


def build_flat(principal: int, rate_bp: int, months: int, anchor: date, emi: int | None = None) -> list[Row]:
    """Flat rate: equal principal and equal interest in every EMI (the last one adjusted).
    An EMI that isn't the formula's (the lender's own) sets the total: EMI × months, the
    part above the amount being interest."""
    total_interest = round(Decimal(principal) * rate_bp * months / Decimal(120_000))
    per_p = principal // months
    if emi and emi != flat_emi(principal, rate_bp, months) and emi * months >= principal:
        total_interest = emi * months - principal
        per_i = total_interest // months
        per_p = emi - per_i  # every EMI is exactly the lender's; the last one takes the paise left
    else:
        per_i = total_interest // months
    total = principal + total_interest
    rows: list[Row] = []
    left_p, left_total = principal, total
    for n in range(1, months + 1):
        last = n == months
        p = left_p if last else per_p
        i = (left_total - left_p) if last else per_i
        left_p -= p
        left_total -= p + i
        rows.append(Row(n, add_months(anchor, n - 1), p + i, p, i, left_p))
    return rows


def build_emi_only(emi: int, months: int, anchor: date) -> list[Row]:
    """Only the EMI is known: no principal/interest split; the balance is what's left to pay."""
    return [Row(n, add_months(anchor, n - 1), emi, emi, 0, emi * (months - n)) for n in range(1, months + 1)]


def implied_rate_bp(principal: int, emi: int, months: int) -> int:
    """The yearly rate (bp) at which `emi` for `months` repays `principal` (reducing balance)."""
    if emi * months <= principal:
        return 0
    lo, hi = 0.0, 100.0  # % a year
    for _ in range(80):
        mid = (lo + hi) / 2
        r = mid / 1200
        f = (1 + r) ** months
        e = principal * r * f / (f - 1)
        if e > emi:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2 * 100)


def schedule_for(
    method: str,
    principal: int | None,
    rate_bp: int | None,
    emi: int,
    months: int,
    first: date,
    first_interest: int | None = None,
    daily: bool = False,
) -> list[Row]:
    """`first_interest` (EMI 1 counted by days) and `daily` (each month's interest on its days)
    apply to reducing-balance loans only."""
    if method == "flat":
        return build_flat(principal or 0, rate_bp or 0, months, first, emi)
    if method == "emi_only" and not principal:
        return build_emi_only(emi, months, first)
    if method == "emi_only":
        rate_bp = implied_rate_bp(principal, emi, months)
    bpi = first_interest if method == "reducing" else None
    return build(
        principal or 0, rate_bp or 0, emi, months, first, first_interest=bpi, daily=daily and method == "reducing"
    )


def what_if(rows: list[Row], paid: int, rate_bp: int, emi: int, amount: int, mode: str, daily: bool = False) -> dict:
    """Part-payment of `amount` made just before the next EMI (reducing balance).
    `mode`: reduce_tenure (same EMI, fewer months) or reduce_emi (same months, lower EMI)."""
    left = rows[paid:]
    if not left:
        raise ValueError("This loan has no EMIs left.")
    outstanding = rows[paid - 1].balance if paid else rows[0].balance + rows[0].principal
    before = {"emi": emi, "months": len(left), "interest": sum(r.interest for r in left), "end_date": left[-1].date}
    new_balance = outstanding - amount
    if new_balance <= 0:
        after = {"emi": 0, "months": 0, "interest": 0, "end_date": None}
    else:
        new_emi = emi if mode == "reduce_tenure" else calc_emi(new_balance, rate_bp, len(left))
        anchor = add_months(left[0].date, -(left[0].n - 1))
        new_rows = build(new_balance, rate_bp, new_emi, len(left), anchor, left[0].n, daily=daily)
        after = {
            "emi": new_emi,
            "months": len(new_rows),
            "interest": sum(r.interest for r in new_rows),
            "end_date": new_rows[-1].date,
        }
    return {
        "outstanding": outstanding,
        "prepay_on": left[0].date,
        "paid_off": new_balance <= 0,
        "before": before,
        "after": after,
        "interest_saved": before["interest"] - after["interest"],
        "months_saved": before["months"] - after["months"],
    }


@dataclass
class Event:
    """A change to a reducing-balance loan, applied before the first EMI dated after it.
    kind "prepay": `amount` paid towards principal; kind "rate": new yearly `rate_bp`.
    mode "reduce_tenure" keeps the EMI (the loan ends sooner / later), "reduce_emi"
    keeps the end date (the EMI is worked out again)."""

    date: date
    kind: str  # prepay | rate
    mode: str  # reduce_tenure | reduce_emi
    amount: int = 0
    rate_bp: int = 0


def build_events(
    principal: int,
    rate_bp: int,
    emi: int,
    tenure: int,
    first: date,
    events: list[Event],
    first_interest: int | None = None,
    daily: bool = False,
) -> tuple[list[Row], list[tuple[Event, int, int]]]:
    """Reducing-balance schedule with part-payments and rate changes. Returns the rows and,
    for each event applied, (event, EMI number it applies before, EMI after it).
    `first_interest` replaces the month's interest of EMI 1 (see first_emi_interest)."""
    pending = sorted(events, key=lambda e: (e.date, e.kind != "rate"))
    rows: list[Row] = []
    applied: list[tuple[Event, int, int]] = []
    balance, n = principal, 1
    while balance > 0 and n <= MAX_MONTHS:
        d = add_months(first, n - 1)
        while pending and pending[0].date < d:
            ev = pending.pop(0)
            if ev.kind == "prepay":
                balance = max(0, balance - ev.amount)
            else:
                rate_bp = ev.rate_bp
            remaining = max(1, tenure - (n - 1))
            if balance > 0 and ev.mode == "reduce_emi":
                emi = calc_emi(balance, rate_bp, remaining)
            applied.append((ev, n, emi))
        if balance <= 0:
            break
        interest = (
            first_interest if n == 1 and first_interest is not None else period_interest(balance, rate_bp, d, daily)
        )
        principal_part = emi - interest
        last_planned = n >= tenure and not any(m in ("reduce_tenure", "close") for m in (e.mode for e, _, _ in applied))
        if principal_part <= 0 and not last_planned:
            raise ValueError(
                f"From {d:%b %Y} the EMI doesn't cover the monthly interest — choose to change the EMI instead."
            )
        if last_planned or principal_part >= balance:
            principal_part = balance
        balance -= principal_part
        rows.append(Row(n, d, principal_part + interest, principal_part, interest, balance))
        n += 1
    for ev in pending:  # after the last EMI (e.g. a final payment)
        applied.append((ev, n, 0))
    return rows, applied

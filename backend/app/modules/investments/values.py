"""What an investment is worth today: one rule per kind. Pure functions, no database.

- Ledger kinds (FD, Post Office lump sums, money lent): every amount put in grows at the
  rate from its own date; amounts taken out stop growing from theirs.
- Schedule kinds (RD, Post Office RD, insurance, chit): instalments are assumed paid on
  their due dates (banks and insurers debit them), up to today.
- Entered kinds (PPF / EPF / NPS / Sukanya, property, other): the value you entered.
- Priced kinds (stocks, crypto): quantity x the price you last entered.
- Gold & silver: grams x the rate you last entered, by purity.
"""

from dataclasses import dataclass, field
from datetime import date

from ...core.dates import add_months

STALE_DAYS = 90
NAV_STALE_DAYS = 10  # fund prices come every working day
PERIODS = {"monthly": 12, "quarterly": 4, "half_yearly": 2, "yearly": 1}
STEP_MONTHS = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}
# Post Office: how interest is added, unless the owner chose otherwise
PO_COMPOUNDING = {
    "nsc": "yearly",
    "kvp": "yearly",
    "td": "quarterly",
    "rd": "quarterly",
    "scss": "payout",
    "mis": "payout",
}
GOLD_PURITY = {"24k": 24 / 24, "22k": 22 / 24, "18k": 18 / 24, "14k": 14 / 24}
SILVER_PURITY = {"999": 1.0, "925": 925 / 999}


@dataclass
class Rates:
    gold_24k: int | None = None  # paise per gram
    silver: int | None = None  # paise per gram (999)
    on: date | None = None  # when the rates were entered


@dataclass
class Due:
    date: date
    what: str  # matures | premium | due_back | instalment
    amount: int


@dataclass
class Valued:
    money_in: int = 0
    money_out: int = 0
    value: int = 0
    value_date: date | None = None
    maturity_value: int | None = None
    paid_count: int | None = None  # schedule kinds: instalments / premiums so far
    total_count: int | None = None
    owed: int = 0  # chit after the payout: instalments still to pay
    stale: bool = False  # a value entered by hand that is over 90 days old
    no_price: bool = False  # priced / gold kinds with no price yet (value = invested)
    dues: list[Due] = field(default_factory=list)

    @property
    def invested(self) -> int:
        return self.money_in - self.money_out

    @property
    def gain(self) -> int:
        return self.value - self.invested


def growth(amount: int, rate_bp: int | None, compounding: str | None, frm: date, to: date) -> int:
    """`amount` put in on `frm`, with interest up to `to`."""
    if not rate_bp or to <= frm or compounding in (None, "payout"):
        return amount
    years = (to - frm).days / 365
    r = rate_bp / 10_000
    if compounding == "simple":
        return round(amount * (1 + r * years))
    n = PERIODS.get(compounding, 4)
    return round(amount * (1 + r / n) ** (n * years))


def compounding_of(inv) -> str | None:
    if inv.compounding:
        return inv.compounding
    if inv.kind == "post_office":
        return PO_COMPOUNDING.get(inv.subtype or "", "quarterly")
    if inv.kind == "lent":
        return "simple"
    if inv.kind in ("fd", "rd"):
        return "quarterly"
    return None


def is_schedule(inv) -> bool:
    return inv.kind in ("rd", "insurance", "chit") or (inv.kind == "post_office" and inv.subtype == "rd")


def schedule_dates(inv) -> list[date]:
    """Due dates of the instalments / premiums, in order."""
    if not inv.start_date:
        return []
    if inv.kind == "insurance":
        if inv.frequency == "single":
            return [inv.start_date]
        step = STEP_MONTHS.get(inv.frequency or "yearly", 12)
        months = inv.months
        if months is None and inv.maturity_date:
            m, s = inv.maturity_date, inv.start_date
            months = (m.year - s.year) * 12 + m.month - s.month
        count = max(1, (months or 12) // step)
    else:
        step, count = 1, inv.months or 0
    return [add_months(inv.start_date, i * step) for i in range(count)]


def maturity_of(inv) -> date | None:
    if inv.maturity_date:
        return inv.maturity_date
    if inv.kind in ("rd", "post_office") and inv.start_date and inv.months:
        return add_months(inv.start_date, inv.months)
    return None


def _ledger(inv, entries: list[tuple[date, int]], today: date, v: Valued) -> None:
    comp = compounding_of(inv)
    mature = maturity_of(inv)
    at = min(today, mature) if mature and inv.kind != "lent" else today
    total = 0
    at_maturity = 0
    for d, amt in entries:
        sign = 1 if amt > 0 else -1
        total += sign * growth(abs(amt), inv.rate_bp, comp, d, max(d, at))
        if mature:
            at_maturity += sign * growth(abs(amt), inv.rate_bp, comp, d, max(d, mature))
    v.value = max(0, total)
    v.value_date = today
    if mature:
        v.maturity_value = inv.maturity_amount or max(0, at_maturity)
        if inv.kind == "lent":
            v.dues.append(Due(mature, "due_back", v.value))
        else:
            v.dues.append(Due(mature, "matures", v.maturity_value))


def _schedule(inv, today: date, v: Valued) -> None:
    dates = schedule_dates(inv)
    paid = [d for d in dates if d <= today]
    amount = inv.instalment or 0
    v.paid_count, v.total_count = len(paid), len(dates)
    v.money_in = amount * len(paid)
    v.value_date = today
    upcoming = [d for d in dates if d > today]
    if inv.kind == "insurance":
        if inv.subtype == "term":
            v.value = v.money_in = 0  # cover only: its premiums are spending
        elif inv.current_value is not None:
            v.value = inv.current_value
            v.value_date = inv.value_date
        else:
            v.value = v.money_in
        if upcoming:
            v.dues.append(Due(upcoming[0], "premium", amount))
        if inv.maturity_date:
            v.maturity_value = inv.maturity_amount or inv.sum_assured
            if inv.subtype != "term":
                v.dues.append(Due(inv.maturity_date, "matures", v.maturity_value or 0))
        return
    if inv.kind == "chit":
        if inv.payout_on:
            v.money_out = inv.payout_amount or 0
            v.owed = amount * len(upcoming)
            v.value = -v.owed  # what's left to pay after taking the payout
        else:
            v.value = v.money_in
        if upcoming:
            v.dues.append(Due(upcoming[0], "instalment", amount))
        return
    # RD: each instalment grows from its due date, quarterly unless chosen otherwise
    comp = compounding_of(inv)
    mature = maturity_of(inv)
    at = min(today, mature) if mature else today
    v.value = sum(growth(amount, inv.rate_bp, comp, d, at) for d in paid)
    if mature:
        v.maturity_value = inv.maturity_amount or sum(growth(amount, inv.rate_bp, comp, d, mature) for d in dates)
        v.dues.append(Due(mature, "matures", v.maturity_value))


def _stale(d: date | None, today: date) -> bool:
    return d is not None and (today - d).days > STALE_DAYS


def value_of(inv, entries: list[tuple[date, int]], today: date, rates: Rates) -> Valued:
    """`entries`: the account's money in (+) and out (-) with dates, the opening balance included."""
    v = Valued()
    if not is_schedule(inv):
        v.money_in = sum(a for _, a in entries if a > 0)
        v.money_out = -sum(a for _, a in entries if a < 0)
    if inv.kind in ("fd", "post_office", "lent") and not is_schedule(inv):
        _ledger(inv, entries, today, v)
    elif is_schedule(inv):
        _schedule(inv, today, v)
    elif inv.kind == "mf":
        f = getattr(inv, "fund", None)
        if f is not None and f.nav is not None:
            v.value = round(f.units * f.nav / 100_000)  # milli-units x 1/10000 rupee -> paise
            v.value_date = f.nav_date
            v.stale = f.nav_date is not None and (today - f.nav_date).days > NAV_STALE_DAYS
        else:
            v.value, v.no_price = max(0, v.invested), True
    elif inv.kind in ("stocks", "crypto"):
        if inv.unit_price is not None and inv.quantity is not None:
            v.value = inv.quantity * inv.unit_price // 1000
            v.value_date = inv.value_date
            v.stale = _stale(inv.value_date, today)
        else:
            v.value, v.no_price = max(0, v.invested), True
    elif inv.kind == "gold":
        silver = inv.subtype == "silver"
        rate = rates.silver if silver else rates.gold_24k
        factor = (
            SILVER_PURITY.get(inv.purity or "999", 1.0)
            if silver
            else (1.0 if inv.subtype in ("sgb", "digital") else GOLD_PURITY.get(inv.purity or "24k", 1.0))
        )
        if rate and inv.quantity:
            v.value = round(inv.quantity * rate * factor / 1000)
            v.value_date = rates.on
            v.stale = _stale(rates.on, today)
        else:
            v.value, v.no_price = max(0, v.invested), True
        if inv.maturity_date:  # SGB
            v.dues.append(Due(inv.maturity_date, "matures", v.value))
    else:  # retirement, property, other
        if inv.current_value is not None:
            v.value = inv.current_value
            v.value_date = inv.value_date
            v.stale = _stale(inv.value_date, today)
        else:
            v.value = max(0, v.invested)
        if inv.maturity_date:
            v.dues.append(Due(inv.maturity_date, "matures", v.value))
    if inv.kind == "insurance" and inv.current_value is not None:
        v.stale = _stale(inv.value_date, today)
    return v

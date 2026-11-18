"""The summary box of a credit card statement: statement date, payment due date,
total and minimum amount due, previous balance. Best effort — every figure is
optional, and the review page only checks what it found.

Layouts seen in Indian card statements:
- "Total Amount Due : Rs. 13,000.00" (label and value on one line)
- a header line of labels with the values on the next line, in the same order:
      Payment Due Date   Total Dues   Minimum Amount Due
      02/12/2026         13,000.00    650.00
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta

MONTHS = {
    m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)
}
NUM_DATE = r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
WORD_DATE = (
    r"\d{1,2}[ -](?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[ ,-]+\d{2,4}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]* \d{1,2},? \d{4}"  # October 18, 2026
)
DATE_TOKEN = re.compile(rf"({NUM_DATE}|{WORD_DATE})", re.I)
MONEY_TOKEN = re.compile(
    r"(?<![\d/-])(?:rs\.?|inr|₹)?\s*(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+\.\d{1,2}|\d+)(?:\s*(cr|dr))?\b", re.I
)

LABELS: dict[str, re.Pattern] = {
    "statement_date": re.compile(r"statement\s+(?:generation\s+)?date|date\s+of\s+statement|bill(?:ing)?\s+date", re.I),
    "due_date": re.compile(r"(?:payment\s+)?due\s+date|pay(?:ment)?\s+by(?:\s+date)?", re.I),
    "total_due": re.compile(
        r"total\s+(?:amount\s+)?dues?|total\s+amount\s+payable|total\s+outstanding|closing\s+balance|new\s+balance",
        re.I,
    ),
    "min_due": re.compile(r"minimum\s+(?:amount\s+)?(?:due|payable)|min\.?\s+(?:amt\.?\s+)?due", re.I),
    "previous_balance": re.compile(
        r"previous\s+(?:statement\s+)?(?:balance|dues?)|opening\s+balance|last\s+statement\s+balance", re.I
    ),
}
DATE_FIELDS = {"statement_date", "due_date"}
PERIOD_RE = re.compile(
    rf"statement\s+period\s*[:\-]?\s*({NUM_DATE}|{WORD_DATE})\s*(?:to|-|–)\s*({NUM_DATE}|{WORD_DATE})", re.I
)


@dataclass
class CardSummary:
    statement_date: date | None = None
    period_start: date | None = None
    due_date: date | None = None
    total_due: int | None = None  # paise
    min_due: int | None = None
    previous_balance: int | None = None  # owed at the start (negative = in credit)

    def any(self) -> bool:
        return any(v is not None for v in self.__dict__.values())


def parse_date(s: str) -> date | None:
    s = s.strip().lower()
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{1,2})[ -]([a-z]{3})[a-z]*[ ,-]+(\d{2,4})", s)
        if m and m.group(2) in MONTHS:
            d, mo, y = int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))
        else:
            m = re.fullmatch(r"([a-z]{3})[a-z]* (\d{1,2}),? (\d{4})", s)
            if not m or m.group(1) not in MONTHS:
                return None
            d, mo, y = int(m.group(2)), MONTHS[m.group(1)], int(m.group(3))
    y = y + 2000 if y < 100 else y
    try:
        out = date(y, mo, d)
    except ValueError:
        return None
    return out if 2000 <= out.year <= 2099 else None


def _money(tok: re.Match) -> int:
    v = round(float(tok.group(1).replace(",", "")) * 100)
    return -v if (tok.group(2) or "").lower() == "cr" else v  # "1,200.00 Cr" = in credit


def _first_value(field: str, text: str):
    if field in DATE_FIELDS:
        m = DATE_TOKEN.search(text)
        return parse_date(m.group(1)) if m else None
    for m in MONEY_TOKEN.finditer(text):
        if "." in m.group(1) or "," in m.group(1):  # a real amount, not a stray number
            return _money(m)
    return None


def _values_in_order(line: str) -> list:
    """Dates and amounts on a line, left to right."""
    out: list[tuple[int, object]] = []
    taken: list[tuple[int, int]] = []
    for m in DATE_TOKEN.finditer(line):
        d = parse_date(m.group(1))
        if d:
            out.append((m.start(), d))
            taken.append(m.span())
    for m in MONEY_TOKEN.finditer(line):
        if any(a <= m.start() < b for a, b in taken):
            continue
        if "." in m.group(1) or "," in m.group(1):
            out.append((m.start(), _money(m)))
    return [v for _, v in sorted(out, key=lambda x: x[0])]


def parse_card_summary(text: str) -> CardSummary:
    s = CardSummary()
    lines = [ln.strip() for ln in text.replace("\r", "").split("\n")]
    head = lines[:150]  # the summary box is near the top
    for i, line in enumerate(head):
        found = sorted(
            ((m.start(), f) for f, rx in LABELS.items() if (m := rx.search(line))),
            key=lambda x: x[0],
        )
        if not found:
            continue
        if len(found) >= 2:
            # a header row of labels: values on this line after the labels, or on the next line
            values = _values_in_order(head[i + 1]) if i + 1 < len(head) else []
            fields = [f for _, f in found]
            if len(values) == len(fields):
                for f, v in zip(fields, values, strict=False):
                    if getattr(s, f) is None and isinstance(v, date) == (f in DATE_FIELDS):
                        setattr(s, f, v)
                continue
        for pos, f in found:
            if getattr(s, f) is not None:
                continue
            rest = line[pos:]
            rest = LABELS[f].sub(" ", rest, count=1)
            v = _first_value(f, rest)
            if v is None and i + 1 < len(head) and not any(rx.search(head[i + 1]) for rx in LABELS.values()):
                v = _first_value(f, head[i + 1])
            if v is not None:
                setattr(s, f, v)
    if m := PERIOD_RE.search(text[:6000]):
        s.period_start = parse_date(m.group(1))
        end = parse_date(m.group(2))
        if s.statement_date is None:
            s.statement_date = end
    _separate_blocks(s, head)
    return s


ALONE_AMOUNT_RE = re.compile(r"(?:rs\.?|inr|₹|Á)?\s*(\d{1,3}(?:,\d{2,3})+\.\d{2}|\d+\.\d{2})", re.I)


def _separate_blocks(s: CardSummary, head: list[str]) -> None:
    """Layouts that print the labels in one block and the values in another, out of order
    (e.g. ICICI: "Total Amount due" / "Minimum Amount due" ... then "₹12,880.00" / "₹46,532.17",
    and the dates as "October 18, 2026" / "November 5, 2026" on lines of their own)."""
    seen = {f for line in head for f, rx in LABELS.items() if rx.search(line)}
    if s.total_due is None and s.min_due is None and {"total_due", "min_due"} <= seen:
        alone = [_money_alone(m.group(1)) for line in head if (m := ALONE_AMOUNT_RE.fullmatch(line))]
        alone = [v for v in alone if v != s.previous_balance]  # already read with its own label
        if len(alone) == 2:  # the total is never below the minimum
            s.total_due, s.min_due = max(alone), min(alone)
    if s.due_date is None and "due_date" in seen and s.statement_date is not None:
        later = [
            d
            for line in head
            if (m := DATE_TOKEN.fullmatch(line)) and (d := parse_date(m.group(1)))
            and s.statement_date < d <= s.statement_date + timedelta(days=60)
        ]
        if later:
            s.due_date = later[0]


def _money_alone(v: str) -> int:
    return round(float(v.replace(",", "")) * 100)

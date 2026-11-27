"""Read a lender's loan statement: a Statement of Account (summary + payments) and / or a
repayment (amortisation) schedule. Text in, loan details out.

Not one layout per lender: values are read after their labels ("Rate of Interest : 9.25%",
or a row of labels with the values on the next line), and a schedule is recognised by its
arithmetic (principal + interest = EMI, the balance falls by the principal). A schedule fills
what the labels miss (amount, tenure, EMI, first EMI date, rate) and is checked against our
own maths, which also tells how the lender counted the first EMI's interest.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median

from ..statements.card_summary import DATE_TOKEN, parse_date
from .maths import calc_emi, first_emi_interest, implied_rate_bp, month_interest, period_interest, schedule_for

RUPEE = 100  # paise

# ------------------------------------------------------------------ labels

# (field, pattern, priority) — at one place in a line the longest label wins; for a field found
# twice the lower priority number wins. Field "_" swallows labels that look like ours but aren't.
_LABELS: list[tuple[str, str, int]] = [
    (
        "loan_number",
        r"loan\s*(?:a/?c|account)\s*(?:no\.?|number|#)?|agreement\s*(?:no\.?|number)|"
        r"loan\s*(?:no\.?|number)|\blan\b|contract\s*(?:no\.?|number)|"
        r"loan\s*proposal\s*/?\s*(?:account\s*)?(?:no\.?|number)",
        0,
    ),  # fmt: skip
    ("principal", r"disburs(?:ed|al|ement)\s*amount|amount\s*disbursed", 0),
    ("principal", r"(?:total\s*|original\s*)?loan\s*amount|amount\s*(?:financed|of\s*loan)|finance\s*amount", 1),
    ("principal", r"sanction(?:ed)?\s*amount|amount\s*sanctioned|sanctioned\s*loan", 2),
    ("principal", r"principal\s*amount", 3),
    (
        "rate_now",
        r"(?:current|revised|present|existing|applicable|effective)\s*(?:roi|rate(?:\s*of\s*interest)?|"
        r"interest\s*rate)",
        0,
    ),  # fmt: skip
    ("rate", r"(?:original|initial|starting)\s*(?:roi|rate(?:\s*of\s*interest)?|interest\s*rate)", 0),
    ("rate", r"rate\s*of\s*interest|interest\s*rate|\broi\b", 1),
    (
        "tenure",
        r"(?:original\s*|total\s*|loan\s*)?(?:tenure|tenor)|loan\s*term|\bterm\b|"
        r"(?:total\s*)?(?:no\.?|number)\s*of\s*(?:e[mp]is|instal?ments|instal?lments)|total\s*(?:emis|instal?l?ments)",
        0,
    ),  # fmt: skip
    (
        "emi",
        r"\be[mp]i(?!s)\s*(?:amount)?|(?:monthly\s*)?instal?l?ment\s*amount|\bemi\s*\(rs\.?\)|"
        r"amount\s*of\s*each\s*e[mp]i",
        0,
    ),  # fmt: skip
    (
        "first_emi_date",
        r"(?:first|1st)\s*(?:emi|instal?l?ment)\s*(?:due\s*)?date|"
        r"(?:emi|instal?l?ment|repayment)\s*(?:start|commencement)\s*date|"
        r"due\s*date\s*of\s*(?:payment\s*of\s*)?(?:first\s*|1st\s*)?instal?l?ment",
        0,
    ),  # fmt: skip
    (
        "disbursed_date",
        r"(?:date\s*of\s*)?disburs(?:al|ement|ed)\s*(?:date|on)|date\s*of\s*disburs(?:al|ement)|"
        r"loan\s*(?:booking|start)\s*date",
        0,
    ),  # fmt: skip
    (
        "last_emi_date",
        r"(?:last|final)\s*(?:emi|instal?l?ment)\s*(?:due\s*)?date|maturity\s*date|" r"(?:emi|loan)\s*end\s*date",
        0,
    ),  # fmt: skip
    (
        "outstanding",
        r"principal\s*(?:amount\s*)?(?:outstanding|o/s)|outstanding\s*principal|\bpos\b|"
        r"balance\s*principal|principal\s*balance|(?:current|loan)\s*outstanding",
        0,
    ),  # fmt: skip
    (
        "emis_paid",
        r"(?:no\.?\s*of\s*)?(?:emis?|instal?l?ments?)\s*(?:paid|received|cleared)|" r"paid\s*(?:emis|instal?l?ments)",
        0,
    ),  # fmt: skip
    (
        "emis_left",
        r"(?:no\.?\s*of\s*)?(?:emis?|instal?l?ments?)\s*(?:remaining|outstanding|pending|balance|left)|"
        r"(?:balance|remaining|residual)\s*(?:tenure|tenor|emis|instal?l?ments|term)",
        0,
    ),  # fmt: skip
    (
        "statement_date",
        r"statement\s*(?:generation\s*)?date|date\s*of\s*statement|\bas\s*on(?:\s*date)?|" r"generated\s*on",
        0,
    ),  # fmt: skip
    ("product", r"product(?:\s*(?:name|type))?|loan\s*type|type\s*of\s*loan|scheme", 0),
    (
        "_",
        r"emi\s*(?:due\s*)?(?:date|day)|emi\s*(?:cycle|frequency|mode|overdue|bounce)|overdue\s*(?:emis?|amount)|"
        r"interest\s*(?:paid|due|type|accrued|charged|component|amount|received)|total\s*interest|rate\s*type|"
        r"principal\s*(?:paid|received|component|due)|(?:emis?|instal?l?ments?)\s*overdue|"
        r"sanction\s*date|"
        # a Key Facts Statement: the amount net of fees, "Upto 24 EMI", the APR
        r"(?:net\s*)?disburs(?:ed|al)\s*amount[^:\n]{0,40}?\bapr\b|net\s*disburs(?:ed|al)\s*amount|"
        r"\b\d{1,3}\s*e[mp]i\b(?!s)|\(e[mp]is?\)|annual\s*percentage\s*rate|annuali[sz]ed\s*interest\s*rate|\bapr\b",
        0,
    ),  # fmt: skip
]
LABELS = [(f, re.compile(p, re.I), pr) for f, p, pr in _LABELS]

KIND_WORDS = [
    ("two_wheeler", r"two[\s-]*wheeler|\bbike\b|motorcycle|scooter"),
    ("home", r"home|housing"),
    ("car", r"\bcar\b|auto|vehicle"),
    ("education", r"education|student"),
    ("gold", r"\bgold\b"),
    ("property", r"against\s*property|\blap\b|mortgage"),
    ("consumer", r"consumer\s*durable|\bcd\s*loan"),
    ("personal", r"personal"),
]

NUM = r"\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d+)?"
MONEY_RE = re.compile(rf"(?<![\d.,])(?:rs\.?|inr|₹)?\s*({NUM})", re.I)
RATE_RE = re.compile(r"(?<![\d.,])(\d{1,2}(?:\.\d{1,4})?)\s*(%|p\.?a)?", re.I)
INT_RE = re.compile(r"(?<![\d.,/-])(\d{1,3})(?![\d,/-]|\.\d)\s*(years?|yrs?|months?|m\b)?", re.I)
NUMBER_ID_RE = re.compile(r"\b([A-Z]{0,8}[0-9][A-Z0-9/-]{4,28})\b", re.I)


def _paise(s: str) -> int:
    return round(float(s.replace(",", "")) * 100)


def _no_dates(s: str) -> str:
    return DATE_TOKEN.sub(lambda m: " " * len(m.group(0)), s)


# "(in Rupees)", "(SI no. 2 of the KFS template)", "(1-6)" hold no value; "(₹ 5,000)" does
PAREN_RE = re.compile(
    r"\((?!\s*(?:(?:rs\.?|inr|₹)\s*[\d,]+(?:\.\d+)?|[\d.]+\s*%|\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d{4,})\s*\))"
    r"[^()]{0,120}\)",
    re.I,
)
ITEM_RE = re.compile(r"^\s*(?:\d{1,2}|[a-h]|[ivx]{1,4})\s*[.)]\s*(?=[A-Za-z])", re.I)  # "5. Installments"
NUMERIC = ("principal", "emi", "outstanding", "rate", "rate_now", "tenure", "emis_paid", "emis_left")


def _clean(kind: str, s: str) -> str:
    """Blank out (same length) what can't hold a numeric field's value."""
    if kind not in NUMERIC:
        return s
    s = PAREN_RE.sub(lambda m: " " * len(m.group(0)), s)
    return ITEM_RE.sub(lambda m: " " * len(m.group(0)), s)


def _value(kind: str, seg: str):
    """The first value of the field's type in `seg` (None = none there)."""
    seg = _clean(kind, seg).strip().lstrip(":-|=").strip()
    if not seg:
        return None
    if kind in ("first_emi_date", "disbursed_date", "last_emi_date", "statement_date"):
        m = DATE_TOKEN.search(seg)
        return parse_date(m.group(1)) if m else None
    if kind == "loan_number":
        for m in NUMBER_ID_RE.finditer(_no_dates(seg)):
            if len(re.sub(r"\D", "", m.group(1))) >= 4:
                return m.group(1).upper()
        return None
    if kind == "product":
        words = re.match(r"[A-Za-z][A-Za-z &/-]{1,40}", seg)
        return words.group(0).strip() if words else None
    s = _no_dates(seg)
    if kind in ("rate", "rate_now"):
        m = RATE_RE.search(s)
        if not m:
            return None
        v = float(m.group(1))
        return round(v * 100) if 0.5 <= v <= 40 else None
    if kind in ("tenure", "emis_paid", "emis_left"):
        m = INT_RE.search(s)
        if not m:
            return None
        n = int(m.group(1)) * (12 if (m.group(2) or "").lower().startswith(("y", "yr")) else 1)
        return n if (0 if kind != "tenure" else 1) <= n <= 600 else None
    m = MONEY_RE.search(s)  # principal / emi / outstanding
    return _paise(m.group(1)) if m else None


def _labels_in(line: str) -> list[tuple[int, int, str, int]]:
    """Non-overlapping label matches in a line, left to right (longest first at a spot)."""
    hits = []
    for f, rx, pr in LABELS:
        for m in rx.finditer(line):
            hits.append((m.start(), m.end(), f, pr))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    inside = [(m.start(), m.end()) for m in re.finditer(r"\([^()]*\)", line)]  # "(Deducted from loan amount)"
    out: list[tuple[int, int, str, int]] = []
    for h in hits:
        if out and h[0] < out[-1][1]:
            continue
        if any(a < h[0] < b for a, b in inside):
            continue
        gap = line[out[-1][1] if out else 0 : h[0]]
        if h[2] in NUMERIC and len(re.findall(r"[A-Za-z]{2,}", PAREN_RE.sub(" ", gap))) >= 4:
            continue  # inside a sentence: "deducted from disbursement amount, please refer … Sr no 8"
        out.append(h)
    return out


AS_ON_RE = re.compile(r"\bas\s*(?:on|of)\s*(?:date\s*)?[:-]?\s*(" + DATE_TOKEN.pattern[1:-1] + ")", re.I)


def kind_word(s: str) -> str | None:
    for k, rx in KIND_WORDS:
        if re.search(rx, s, re.I):
            return k
    return None


def read_labels(lines: list[str]) -> dict[str, object]:
    found: dict[str, tuple[int, object]] = {}

    def keep(f: str, pr: int, v) -> None:
        if f != "_" and v is not None and (f not in found or pr < found[f][0]):
            found[f] = (pr, v)

    for i, raw in enumerate(lines):
        if DATE_TOKEN.match(raw.strip()):
            continue  # a dated entry or schedule row, not a label
        line = raw
        for m in AS_ON_RE.finditer(raw):  # "Principal outstanding as on 15/11/2026 : 5,12,345"
            keep("statement_date", 1, parse_date(m.group(1)))
            line = line.replace(m.group(0), " " * len(m.group(0)))
        hits = _labels_in(line)
        if not hits:
            continue
        segs = [line[h[1] : (hits[k + 1][0] if k + 1 < len(hits) else len(line))] for k, h in enumerate(hits)]
        values = [_value(h[2], s) if h[2] != "_" else None for h, s in zip(hits, segs, strict=True)]
        nxt = next((ln for ln in lines[i + 1 : i + 3] if ln.strip()), "")
        if all(v is None for v in values) and nxt and not _labels_in(nxt):
            # a row of labels, the values on the next line in the same order
            rest = nxt
            for h in hits:
                if h[2] == "_":
                    continue
                v = _value(h[2], rest)
                if v is None:
                    continue
                keep(h[2], h[3], v)
                rest = _after_value(h[2], rest)
            continue
        for h, v in zip(hits, values, strict=True):
            keep(h[2], h[3], v)
    return {f: v for f, (_, v) in found.items()}


def _after_value(kind: str, s: str) -> str:
    """`s` after the first value of the field's type (for a row of values)."""
    s = _clean(kind, s)
    if kind.endswith("_date"):
        m = DATE_TOKEN.search(s)
    elif kind == "loan_number":
        m = NUMBER_ID_RE.search(_no_dates(s))
    elif kind in ("rate", "rate_now"):
        m = RATE_RE.search(_no_dates(s))
    elif kind in ("tenure", "emis_paid", "emis_left"):
        m = INT_RE.search(_no_dates(s))
    elif kind == "product":
        m = re.search(r"[A-Za-z][A-Za-z &/-]{1,40}", s)
    else:
        m = MONEY_RE.search(_no_dates(s))
    return s[m.end() :] if m else s


# ------------------------------------------------------------------ schedule


@dataclass
class SchedRow:
    n: int
    date: date
    emi: int
    principal: int
    interest: int
    balance: int | None  # left after this EMI
    opening: int | None = None


SCHED_LINE_RE = re.compile(r"^\s*(?:(\d{1,3})[.)]?\s+)?(" + DATE_TOKEN.pattern[1:-1] + r")\s+(.*)$", re.I)
NUM_TOKEN_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+\.\d{1,4}|\d+)(?![\d.])")
STATUS_RE = re.compile(r"^(?:rs\.?|inr|₹|%|-|\||paid|due|unpaid|pending|cleared|billed|future|\s)*$", re.I)


def _sched_lines(lines: list[str]) -> list[tuple[int | None, date, list[int]]]:
    out = []
    for line in lines:
        m = SCHED_LINE_RE.match(line)
        if not m:
            continue
        d = parse_date(m.group(2))
        rest = m.group(3)
        if d is None or not STATUS_RE.match(NUM_TOKEN_RE.sub(" ", rest)):
            continue  # words between the numbers: a statement entry, not a schedule row
        nums = [_paise(t) for t in NUM_TOKEN_RE.findall(rest)]
        if len(nums) >= 3:
            out.append((int(m.group(1)) if m.group(1) else None, d, nums))
    return out


def _near(a: int, b: int, tol: int = RUPEE) -> bool:
    return abs(a - b) <= tol


def read_schedule(lines: list[str]) -> list[SchedRow]:
    cand = _sched_lines(lines)
    if len(cand) < 3:
        return []
    # which columns are (EMI, part, part): two numbers that add up to a third, in most rows
    triples: Counter = Counter()
    for _, _, v in cand:
        seen = set()
        for e in range(len(v)):
            for a in range(len(v)):
                for b in range(a + 1, len(v)):
                    if len({e, a, b}) == 3 and v[e] > 0 and _near(v[a] + v[b], v[e]):
                        seen.add((e, a, b))
        triples.update(seen)
    if not triples:
        return []
    (e, a, b), hits = triples.most_common(1)[0]
    if hits < 3:
        return []
    rows = [(n, d, v) for n, d, v in cand if max(e, a, b) < len(v) and _near(v[a] + v[b], v[e])]
    width = Counter(len(v) for _, _, v in rows).most_common(1)[0][0]
    rows = [r for r in rows if len(r[2]) == width]
    others = [i for i in range(width) if i not in (e, a, b)]

    # the principal is the part the balance falls by
    def fits(p: int, c: int) -> int:
        return sum(1 for k in range(1, len(rows)) if _near(rows[k - 1][2][c] - rows[k][2][p], rows[k][2][c]))

    best = None  # (score, principal idx, interest idx, closing idx)
    for p, i in ((a, b), (b, a)):
        for c in others:
            sc = fits(p, c)
            if sc and (best is None or sc > best[0]):
                best = (sc, p, i, c)
    if best:
        _, p, i, c = best
        o = next((x for x in others if x != c and all(_near(v[x] - v[p], v[c]) for _, _, v in rows[:5])), None)
    else:  # no balance column: the principal part grows over a loan (or the header says so)
        p, i = (a, b) if rows[-1][2][a] >= rows[0][2][a] else (b, a)
        c = o = None
    out, seq = [], 0
    for n, d, v in rows:
        seq = n if n is not None else seq + 1
        out.append(
            SchedRow(
                n=seq,
                date=d,
                emi=v[e],
                principal=v[p],
                interest=v[i],
                balance=v[c] if c is not None else None,
                opening=v[o] if o is not None else None,
            )
        )
    # one table: numbers rise one by one (drop a stray earlier / repeated row)
    clean: list[SchedRow] = []
    for r in out:
        if not clean or r.n == clean[-1].n + 1 and r.date > clean[-1].date:
            clean.append(r)
        elif r.n == 1 and len(clean) < 3:
            clean = [r]
    return clean if len(clean) >= 3 else []


# ------------------------------------------------------------------ statement entries

PREPAY_RE = re.compile(
    r"part\s*-?\s*(?:pre\s*-?\s*)?payment|pre\s*-?\s*payment|prepay|part\s*pay|foreclos|lump\s*sum|"
    r"principal\s*(?:pre)?payment",
    re.I,
)
CHARGE_RE = re.compile(r"charge|fee|gst|penal|interest\s+on", re.I)
RATE_CHANGE_RE = re.compile(
    r"(?:roi|rate\s*of\s*interest|interest\s*rate).{0,80}(?:chang|revis|reset|modif|w\.?\s*e\.?\s*f|effective)|"
    r"(?:revised|new)\s*(?:roi|rate)",
    re.I,
)
RATE_PCT_RE = re.compile(r"(\d{1,2}(?:\.\d{1,4})?)\s*%")
WHEN_RE = re.compile(r"(?:w\.?\s*e\.?\s*f\.?|from|effective)\D{0,12}(" + DATE_TOKEN.pattern[1:-1] + ")", re.I)
EMI_PAID_RE = re.compile(r"(?:emi|instal?l?ment).{0,40}(?:received|paid|recd|receipt|credit|cleared|nach|ecs)|"
                         r"(?:received|recd|receipt|nach|ecs).{0,40}(?:emi|instal?l?ment)", re.I)  # fmt: skip


@dataclass
class Found:
    """A part-payment or a rate change read from the statement (or seen in the schedule)."""

    kind: str  # prepay | rate
    date: date
    amount: int | None = None  # prepay
    rate_bp: int | None = None  # rate
    mode: str = "reduce_tenure"
    source: str = "statement"  # statement | schedule (the date is then the EMI it shows up before)
    text: str = ""


def read_entries(lines: list[str]) -> tuple[list[Found], list[tuple[date, int]]]:
    """Part-payments and rate changes in the statement's entries, plus EMI receipts (date, amount)."""
    found: list[Found] = []
    receipts: list[tuple[date, int]] = []
    for line in lines:
        dm = DATE_TOKEN.search(line)
        if not dm or not (on := parse_date(dm.group(1))):
            continue
        rest = line[dm.end() :]
        if RATE_CHANGE_RE.search(line):
            rates = [float(x) for x in RATE_PCT_RE.findall(line) if 0.5 <= float(x) <= 40]
            when = WHEN_RE.search(line)
            if rates:
                d = parse_date(when.group(1)) if when else on
                found.append(Found("rate", d or on, rate_bp=round(rates[-1] * 100), text=line.strip()))
            continue
        if PREPAY_RE.search(rest) and not CHARGE_RE.search(rest):
            m = MONEY_RE.search(_no_dates(rest[PREPAY_RE.search(rest).end() :]))
            if m and (amt := _paise(m.group(1))) >= 1000 * RUPEE:
                found.append(Found("prepay", on, amount=amt, text=line.strip()))
            continue
        if EMI_PAID_RE.search(rest):
            m = MONEY_RE.search(_no_dates(rest))
            if m:
                receipts.append((on, _paise(m.group(1))))
    return found, receipts


# ------------------------------------------------------------------ the whole statement

LOAN_HINT_RE = re.compile(r"repayment\s*schedule|amorti[sz]ation\s*(?:schedule|table)|loan\s*statement|"
                          r"statement\s*of\s*(?:loan\s*)?account", re.I)  # fmt: skip


@dataclass
class LoanStatement:
    values: dict[str, object] = field(default_factory=dict)  # field -> value
    from_labels: set[str] = field(default_factory=set)
    worked_out: set[str] = field(default_factory=set)  # filled from the schedule / the other figures
    schedule: list[SchedRow] = field(default_factory=list)
    found: list[Found] = field(default_factory=list)
    receipts: list[tuple[date, int]] = field(default_factory=list)
    check: dict | None = None  # the schedule against our maths
    notes: list[str] = field(default_factory=list)

    def get(self, k: str):
        return self.values.get(k)

    def put(self, k: str, v) -> None:
        if v is not None and self.values.get(k) is None:
            self.values[k] = v
            self.worked_out.add(k)

    def score(self) -> int:
        return len(self.from_labels) * 3 + min(len(self.schedule), 30)


CORE = {"loan_number", "principal", "emi", "tenure", "rate", "rate_now", "first_emi_date", "disbursed_date",
        "outstanding", "emis_paid", "emis_left"}  # fmt: skip


def is_loan_statement(text: str) -> bool:
    """A lender's loan statement or repayment schedule (not a bank / card statement)."""
    head = text[:6000]
    by_line = [{f for _, _, f, _ in _labels_in(ln)} & CORE for ln in head.splitlines()]
    core = set().union(*by_line) if by_line else set()
    lines_with = sum(1 for x in by_line if x)
    if re.search(r"credit\s*limit|available\s*credit|minimum\s*amount\s*due", head, re.I):
        return False  # a card statement mentions EMIs and rates too
    if LOAN_HINT_RE.search(head) and (len(core) >= 2 or len(read_schedule(text.splitlines())) >= 6):
        return True
    # a card's EMI table has a row of loan words too: a loan statement has its number or rate,
    # and its details on several lines
    return len(core) >= 4 and lines_with >= 3 and bool(core & {"loan_number", "rate", "rate_now"})


def kind_of(text: str) -> str | None:
    head = text[:4000]
    for k, rx in KIND_WORDS:
        if re.search(rf"(?:{rx})[\w\s-]{{0,12}}loan|loan[\w\s-]{{0,8}}(?:{rx})", head, re.I):
            return k
    return None


def lender_of(text: str, names: list[str]) -> str | None:
    head = text[:4000].lower()
    hits = [(head.find(n.lower()), n) for n in names if n and n.lower() in head]
    return min(hits)[1] if hits else None


def parse_loan_statement(text: str, lenders: list[str] | None = None, today: date | None = None) -> LoanStatement:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    st = LoanStatement()
    labels = read_labels(lines)
    st.values = dict(labels)
    st.from_labels = set(labels)
    if "product" in st.values:
        st.values["kind"] = kind_word(str(st.values.pop("product"))) or kind_of(text)
        st.from_labels.discard("product")
    else:
        st.values["kind"] = kind_of(text)
    if st.values["kind"]:
        st.from_labels.add("kind")
    if lenders and (who := lender_of(text, lenders)):
        st.values["lender"] = who
        st.from_labels.add("lender")
    st.schedule = read_schedule(lines)
    if not st.schedule:  # a two-lines-per-EMI ledger (Bandhan); other layouts never get here
        st.schedule = read_ledger_schedule(lines)
        if st.schedule:
            _ledger_extras(st, text)
    st.found, st.receipts = read_entries(lines)
    _work_out(st, today or date.today())
    _emi_check(st, text)
    return st


# ------------------------------------------------------------------ ledger-style schedule
# Some lenders (e.g. Bandhan) list each EMI as two lines on the same date: the repayment of the
# whole EMI (the balance falls by it), then the month's interest added to the balance:
#   01/02/23  Repayment of loan              12719  12719  586409
#   01/02/23  Debit - Capitalize Def Int      4783   4783  591192
# Read only when the usual reader finds no schedule, so other layouts are untouched.

LEDGER_LINE_RE = re.compile(r"^\s*(" + DATE_TOKEN.pattern[1:-1] + r")\s+(.*)$", re.I)
LEDGER_NUM_RE = re.compile(r"-?\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|-?\d+(?:\.\d{1,2})?")
LEDGER_PAY_RE = re.compile(r"repayment|payoff|pay\s*off|\bemi\b|instal?l?ment\s*(?:paid|received|collected)", re.I)
LEDGER_INT_RE = re.compile(r"interest|\bint\b|capitali[sz]", re.I)
ACCOUNT_NO_RE = re.compile(r"account\s*(?:number|no\.?)\s*[:.-]?\s*([0-9]{6,20})\b", re.I)
REQUESTED_RE = re.compile(
    r"(?:amount\s*requested|loan\s*amount|amount\s*financed)\s*[:.-]?\s*(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    re.I,
)


def _ledger_rows(lines: list[str]) -> list[tuple[date, str, int, int | None]]:
    """(date, what, amount, balance after) for dated lines with an activity: what = pay | int | open."""
    out = []
    for raw in lines:
        m = LEDGER_LINE_RE.match(raw)
        if not m:
            continue
        on = parse_date(m.group(1))
        if on is None:
            continue
        rest = m.group(m.lastindex or 2)
        words = re.sub(r"[-\d.,\s]+", " ", rest).strip()
        nums = [n for n in LEDGER_NUM_RE.findall(rest)]
        if len(nums) < 2:
            continue
        amount = _paise(nums[0].lstrip("-"))
        balance = _paise(nums[-1].lstrip("-")) * (-1 if nums[-1].startswith("-") else 1)
        if not words and amount == 0:
            out.append((on, "open", 0, balance))
        elif LEDGER_INT_RE.search(words) and not LEDGER_PAY_RE.search(words):
            out.append((on, "int", amount, balance))
        elif LEDGER_PAY_RE.search(words):
            out.append((on, "pay", amount, balance))
    return out


def read_ledger_schedule(lines: list[str]) -> list[SchedRow]:
    """EMIs from repayment + interest line pairs (same date). Needs at least 6 of them."""
    rows = _ledger_rows(lines)
    pays = [r for r in rows if r[1] == "pay"]
    ints = [r for r in rows if r[1] == "int"]
    if len(pays) < 6 or len(ints) < len(pays) // 2:
        return []
    out: list[SchedRow] = []
    i = 0
    while i < len(rows):
        on, what, amount, bal = rows[i]
        if what != "pay":
            i += 1
            continue
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        interest, after = 0, bal
        if nxt and nxt[1] == "int" and nxt[0] == on:
            interest, after = nxt[2], nxt[3]
            i += 1
        opening = (bal or 0) + amount  # before the repayment
        out.append(SchedRow(len(out) + 1, on, amount, amount - interest, interest, max(0, after or 0), opening))
        i += 1
    return out if len(out) >= 6 else []


def _ledger_extras(st: "LoanStatement", text: str) -> None:
    """A ledger schedule's loan number and amount, when the labels didn't give them."""
    v = st.values
    # the schedule itself says how many EMIs, when the last is and what's left — a header such as
    # "Principal Balance" or a term / maturity counted from the loan date is less exact
    for k in ("tenure", "last_emi_date", "outstanding"):
        if k in st.from_labels:
            v.pop(k, None)
            st.from_labels.discard(k)
    if not v.get("loan_number") and (m := ACCOUNT_NO_RE.search(text)):
        v["loan_number"] = m.group(1)
        st.from_labels.add("loan_number")
    if not v.get("principal") and (m := REQUESTED_RE.search(text)):
        v["principal"] = _paise(m.group(1))
        st.from_labels.add("principal")


def _rate_of(r: SchedRow, opening: int) -> float | None:
    return r.interest * 120_000 / opening if opening >= 10_000 * RUPEE else None


def _snap(bp: float) -> int:
    """Lenders' rates are usually in steps of 0.05%."""
    five = round(bp / 5) * 5
    return five if abs(five - bp) <= 2 else round(bp)


def _rates_by_days(s: list[SchedRow]) -> list[tuple[SchedRow, float]] | None:
    """The yearly rate from each EMI's interest counted on the days since the previous EMI, when that
    is steady while the rate/12 reading jumps with the month's length (28 vs 31 days). None when
    rate/12 fits — then nothing changes."""
    month, days = [], []
    for k in range(1, min(len(s), 13)):
        opening = s[k].opening or s[k - 1].balance
        n_days = (s[k].date - s[k - 1].date).days
        if not opening or opening < 10_000 * RUPEE or not 27 <= n_days <= 32:
            continue
        month.append(s[k].interest * 120_000 / opening)
        days.append((s[k], s[k].interest * 3_650_000 / (opening * n_days)))
    if len(days) < 4:
        return None
    m_spread = max(month) - min(month)
    d_spread = max(bp for _, bp in days) - min(bp for _, bp in days)
    if m_spread < 15 or d_spread > 3:
        return None
    out = []
    for k in range(1, len(s)):
        opening = s[k].opening or s[k - 1].balance
        n_days = (s[k].date - s[k - 1].date).days
        if opening and opening >= 10_000 * RUPEE and 27 <= n_days <= 32:
            out.append((s[k], s[k].interest * 3_650_000 / (opening * n_days)))
    return out


def _work_out(st: LoanStatement, today: date) -> None:
    v, s = st.values, st.schedule
    if "rate_now" in v and "rate" not in v:
        v["rate"] = v["rate_now"]
        st.from_labels.add("rate")
    if s:
        first = s[0]
        whole = first.n == 1
        if whole:
            st.put("first_emi_date", first.date)
            opening = first.opening or (first.balance + first.principal if first.balance is not None else None)
            st.put("principal", opening)
        if s[-1].balance is not None and s[-1].balance <= RUPEE:
            st.put("tenure", s[-1].n)
            st.put("last_emi_date", s[-1].date)
        st.put("emi", Counter(r.emi for r in s[: max(3, len(s) - 1)]).most_common(1)[0][0])
        # the yearly rate from the interest on each month's opening balance
        rates: list[tuple[SchedRow, float]] = []
        for k in range(1, len(s)):
            opening = s[k].opening or s[k - 1].balance
            if opening and (bp := _rate_of(s[k], opening)) is not None:
                rates.append((s[k], bp))
        if len({r.interest for r in s}) == 1 and len({r.principal for r in s}) == 1 and whole:
            v.setdefault("method", "flat")
            if st.values.get("principal"):
                st.put("rate", _snap(first.interest * 120_000 / int(st.values["principal"])))  # type: ignore[arg-type]
        elif rates:
            by_days = _rates_by_days(s)
            if by_days is not None:  # each month's interest on its actual days (365-day year)
                v["interest_basis"] = "days365"
                rates = by_days
            start = _snap(median(bp for _, bp in rates[:3]))
            label = v.get("rate")
            if label is not None and abs(int(label) - start) > 5:  # type: ignore[arg-type]
                v.setdefault("rate_now", label)  # the statement's rate is today's; the schedule shows the start
                st.from_labels.add("rate_now")
                st.from_labels.discard("rate")
                v["rate"] = start
                st.worked_out.add("rate")
            st.put("rate", start)
            v["rate_start"] = start  # the schedule's: the loan's starting rate for sure
            _changes_from_schedule(st, rates)
        _prepays_from_schedule(st)
        statement_on = v.get("statement_date") or today
        done = [r for r in s if r.date <= statement_on]
        if done and done[-1].balance is not None:
            st.put("outstanding", done[-1].balance)
        if whole:
            st.put("emis_paid", len(done))
    v.setdefault("method", "reducing")
    p, rate, tenure, emi = v.get("principal"), v.get("rate"), v.get("tenure"), v.get("emi")
    if tenure is None and v.get("emis_paid") is not None and v.get("emis_left") is not None:
        st.put("tenure", int(v["emis_paid"]) + int(v["emis_left"]))
    tenure = v.get("tenure")
    if rate is None and p and emi and tenure:
        st.put("rate", implied_rate_bp(int(p), int(emi), int(tenure)))
    if st.receipts and v.get("emis_paid") is None and emi:
        paid = {(d.year, d.month) for d, a in st.receipts if _near(a, int(emi), 2 * RUPEE)}
        if paid:
            st.put("emis_paid", len(paid))
    if "first_emi_date" not in v and v.get("last_emi_date") and tenure:
        last: date = v["last_emi_date"]  # type: ignore[assignment]
        st.put("first_emi_date", _add_months(last, -(int(tenure) - 1)))
    _first_interest(st)
    if v.get("tenure") is None and s and s[0].n == 1 and p and emi and v.get("rate") is not None:
        st.put("tenure", _months_to_repay(int(p), int(v["rate"]), int(emi), s[0].interest))  # type: ignore[arg-type]
    _check(st)
    _dedupe(st)


def _emi_check(st: LoanStatement, text: str) -> None:
    """No schedule: the EMI follows from amount, rate and tenure. One far off was misread
    ("Upto 24 EMI"): take the amount in the text that matches the maths, else the maths."""
    v = st.values
    p, rate, tenure, emi = v.get("principal"), v.get("rate"), v.get("tenure"), v.get("emi")
    if st.schedule or not (p and rate and tenure) or v.get("method") != "reducing":
        return
    want = calc_emi(int(p), int(rate), int(tenure))  # type: ignore[arg-type]
    if emi is None or abs(int(emi) - want) > want // 10:  # type: ignore[arg-type]
        # (within 10%: rounding, a longer first month or a rate that has moved since — keep it)
        # a first EMI with more than a month's interest makes it a little higher than the formula
        tol = max(10 * RUPEE, want // 40)
        seen = [_paise(m.group(1)) for m in MONEY_RE.finditer(_no_dates(text))]
        times = Counter(a for a in seen if _near(a, want, tol))
        close = sorted(times, key=lambda a: (-times[a], abs(a - want)))  # the EMI is usually printed more than once
        v.pop("emi", None)
        st.from_labels.discard("emi")
        st.worked_out.discard("emi")
        if close:
            v["emi"] = close[0]
            st.from_labels.add("emi")
        else:
            st.put("emi", want)
    _first_interest_from_emi(st, text, want)


COMMENCE_RE = re.compile(r"commencement\s*of\s*repayment.{0,160}?\b(\d{1,3})\s*days", re.I | re.S)


def _first_interest_from_emi(st: LoanStatement, text: str, plain: int) -> None:
    """No schedule: which first-EMI interest gives the lender's EMI. A Key Facts Statement says
    "Commencement of repayment, post sanction: 50 days" — the days of interest in EMI 1."""
    v = st.values
    emi, first = v.get("emi"), v.get("first_emi_date")
    if emi is None or "first_interest" in v:
        return
    emi = int(emi)  # type: ignore[arg-type]
    if _near(emi, plain, 2 * RUPEE):
        st.put("first_interest", "month")
        return
    if not isinstance(first, date):
        return
    p, rate, tenure = int(v["principal"]), int(v["rate"]), int(v["tenure"])  # type: ignore[arg-type]
    taken: list[date] = [v["disbursed_date"]] if isinstance(v.get("disbursed_date"), date) else []  # type: ignore[list-item]
    if not taken and (m := COMMENCE_RE.search(text)) and 1 <= int(m.group(1)) <= 75:
        taken.append(first - timedelta(days=int(m.group(1))))
    for on in taken:
        for mode in ("days365", "days360"):
            bpi = first_emi_interest(p, rate, first, on, mode)
            if bpi is not None and _near(calc_emi(p, rate, tenure, bpi), emi, 2 * RUPEE):
                st.put("first_interest", mode)
                st.put("disbursed_date", on)
                return


def _months_to_repay(principal: int, rate_bp: int, emi: int, first_interest: int) -> int | None:
    """EMIs until the balance is cleared (a schedule that stops part-way)."""
    bal, k = principal, 0
    while bal > RUPEE and k < 600:
        bal += (first_interest if k == 0 else month_interest(bal, rate_bp)) - emi
        k += 1
    return k if bal <= RUPEE else None


def _add_months(d: date, k: int) -> date:
    m = d.month - 1 + k
    y, m = d.year + m // 12, m % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, 28)


def _changes_from_schedule(st: LoanStatement, rates: list[tuple[SchedRow, float]]) -> None:
    """A rate that moves and stays moved (3 EMIs in a row) is a rate change before that EMI."""
    s = st.schedule
    cur = median(bp for _, bp in rates[:3])
    k = 3
    while k + 2 < len(rates):
        window = [bp for _, bp in rates[k : k + 3]]
        new = median(window)
        if abs(new - cur) > 10 and all(abs(x - new) <= 5 for x in window):
            row = rates[k][0]
            prev = next((r for r in s if r.n == row.n - 1), None)
            before = prev.emi if prev else row.emi
            st.found.append(
                Found(
                    "rate",
                    (prev.date + timedelta(days=1)) if prev else row.date,
                    rate_bp=_snap(new),
                    mode="reduce_tenure" if _near(row.emi, before) else "reduce_emi",
                    source="schedule",
                )
            )
            cur = new
            k += 3
        else:
            k += 1


def _prepays_from_schedule(st: LoanStatement) -> None:
    """The balance dropping by more than the EMI's principal between two EMIs."""
    s = st.schedule
    for k in range(1, len(s)):
        opening = s[k].opening
        before = s[k - 1].balance
        if opening is None or before is None or before - opening < 1000 * RUPEE:
            continue
        after = s[k + 1].emi if k + 1 < len(s) else s[k].emi
        st.found.append(
            Found(
                "prepay",
                s[k - 1].date + timedelta(days=1),
                amount=before - opening,
                mode="reduce_tenure" if _near(after, s[k - 1].emi) else "reduce_emi",
                source="schedule",
            )
        )


def _dedupe(st: LoanStatement) -> None:
    """The same change in the entries and the schedule: keep the entry (its date is exact)."""
    keep: list[Found] = []
    for f in sorted(st.found, key=lambda f: (f.source != "statement", f.date)):
        twin = next(
            (
                k
                for k in keep
                if k.kind == f.kind
                and abs((k.date - f.date).days) <= 45
                and (k.amount is None or f.amount is None or _near(k.amount, f.amount, 100 * RUPEE))
                and (k.rate_bp is None or f.rate_bp is None or abs(k.rate_bp - f.rate_bp) <= 5)
            ),
            None,
        )
        if twin is None:
            keep.append(f)
        elif twin.source == "statement" and f.source == "schedule":
            twin.mode = f.mode  # the schedule shows what the change did
    keep.sort(key=lambda f: f.date)
    st.found = keep


def _first_interest(st: LoanStatement) -> None:
    """How the first EMI's interest was counted: a month, or the days since the loan was paid
    out on a 365 / 360-day year (then the taken-on date can be worked out too)."""
    v, s = st.values, st.schedule
    p, rate = v.get("principal"), v.get("rate")
    if not s or s[0].n != 1 or not p or not rate or v.get("method") != "reducing":
        return
    first, got = s[0].date, s[0].interest
    daily = v.get("interest_basis") == "days365"
    if daily and s[0].opening and s[0].opening > int(p):  # interest added to the balance before EMI 1
        got += s[0].opening - int(p)  # type: ignore[operator]
    normal = period_interest(int(p), int(rate), first, True) if daily else month_interest(int(p), int(rate))
    if _near(got, normal, 2 * RUPEE):
        st.put("first_interest", "month")
        return
    taken = v.get("disbursed_date")
    if taken:
        for mode in ("days360", "days365"):
            bpi = first_emi_interest(int(p), int(rate), first, taken, mode)  # type: ignore[arg-type]
            if bpi is not None and _near(bpi, got, 2 * RUPEE):
                st.put("first_interest", mode)
                return
        return
    best = None
    for mode, year in (("days360", 360), ("days365", 365)):
        days = got * year * 10_000 / (int(p) * int(rate))
        off = abs(days - round(days))
        if 1 <= round(days) <= 75 and off <= 0.2 and (best is None or off < best[0]):
            best = (off, mode, round(days))
    if best:
        st.put("first_interest", best[1])
        st.put("disbursed_date", first - timedelta(days=best[2]))


def _check(st: LoanStatement) -> None:
    """Our schedule from these terms, against the lender's (up to the first change)."""
    v, s = st.values, st.schedule
    p, rate, emi, tenure, first = (v.get(k) for k in ("principal", "rate", "emi", "tenure", "first_emi_date"))
    if not s or s[0].n != 1 or not (p and emi and tenure and first) or s[0].balance is None:
        return
    bpi = None
    mode = v.get("first_interest", "month")
    if v["method"] == "reducing" and mode != "month":
        bpi = first_emi_interest(int(p), int(rate or 0), first, v.get("disbursed_date"), str(mode))  # type: ignore[arg-type]
    try:
        ours = schedule_for(
            str(v["method"]), int(p), int(rate or 0), int(emi), int(tenure), first, bpi,  # type: ignore[arg-type]
            daily=v.get("interest_basis") == "days365",
        )  # fmt: skip
    except ValueError:
        return
    stop = min((f.date for f in st.found), default=None)
    pairs = [(r, o) for r, o in zip(s, ours, strict=False) if r.balance is not None and (stop is None or r.date < stop)]
    if not pairs:
        return
    worst = max(abs(r.balance - o.balance) for r, o in pairs)  # type: ignore[operator]
    st.check = {
        "rows": len(pairs),
        "max_diff": worst,
        "matches": worst <= max(10 * RUPEE, int(p) // 1000),
    }

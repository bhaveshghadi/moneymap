"""Reader for the CAMS + KFintech Consolidated Account Statement (CAS) PDF text.

Detailed CAS layout (per fund):
    <AMC> Mutual Fund
    Folio No: 1234567/89   PAN: …
    <code>-<scheme name> - ISIN: INF…(Advisor: …) Registrar : CAMS
    Opening Unit Balance: 0.000
    05-Jan-2024   Systematic Investment (1)   4,999.75   49.997   100.0000   49.997
    05-Jan-2024   *** Stamp Duty ***   0.25
    10-Mar-2024   Redemption   (2,200.00)   (20.000)   110.0000   75.449
    Closing Unit Balance: 75.449   NAV on 10-Nov-2026: INR 125.5000   Total Cost Value: 7,799.50
    Market Value on 10-Nov-2026: INR 9,468.85

Amounts are integer paise, units integer milli-units (3 decimals), NAV in
1/10000 rupee (4 decimals). Money sign is from the fund's side: + money into
the fund (purchase), − money out (redemption).
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime

DATE = r"\d{2}-[A-Za-z]{3}-\d{4}"
NUM = r"\(?-?[\d,]*\d\.\d+\)?"
TXN_RE = re.compile(rf"^({DATE})\s+(.+?)\s+({NUM})\s+({NUM})\s+({NUM})\s+({NUM})\s*$")
TAX_RE = re.compile(rf"^({DATE})\s+\*+\s*(.+?)\s*\*+\s*({NUM})?\s*$")
DATE_LEAD_RE = re.compile(rf"^({DATE})\b")
AMC_RE = re.compile(r"^([A-Za-z0-9&.' -]+?\s(?:Mutual Fund|MF))\s*$", re.I)
FOLIO_RE = re.compile(r"Folio\s*No\s*[:.]?\s*([A-Za-z0-9/ -]+?)(?:\s{2,}|\s+PAN\b|\s+KYC\b|$)", re.I)
ISIN_RE = re.compile(r"ISIN\s*[:.]?\s*(IN[A-Z0-9]{10})", re.I)
REGISTRAR_RE = re.compile(r"Registrar\s*:\s*([A-Za-z]+)", re.I)
OPENING_RE = re.compile(r"Opening\s+Unit\s+Balance\s*:\s*(" + NUM + ")", re.I)
CLOSING_RE = re.compile(r"Closing\s+Unit\s+Balance\s*:\s*(" + NUM + ")", re.I)
NAV_RE = re.compile(rf"NAV\s+on\s+({DATE})\s*:\s*INR\s*({NUM})", re.I)
COST_RE = re.compile(r"Total\s+Cost\s+Value\s*:\s*(" + NUM + ")", re.I)
MARKET_RE = re.compile(rf"Market\s+Value\s+on\s+({DATE})\s*:\s*INR\s*({NUM})", re.I)
PERIOD_RE = re.compile(rf"({DATE})\s+(?:To|-)\s+({DATE})", re.I)
CAS_RE = re.compile(r"consolidated\s+account\s+statement", re.I)


@dataclass
class CasTxn:
    date: date
    description: str
    kind: str  # purchase | sip | redemption | switch_in | switch_out | dividend_reinvest | dividend_payout | reversal
    amount: int  # paise, + into the fund
    units: int  # milli-units, signed
    nav: int  # 1/10000 rupee
    balance: int  # milli-units after this row
    stamp_duty: int = 0  # paise charged with this purchase (bank debit = amount + stamp duty)


@dataclass
class CasFund:
    amc: str
    folio: str
    scheme: str
    isin: str | None
    registrar: str | None = None
    opening_units: int = 0
    closing_units: int | None = None
    nav: int | None = None
    nav_date: date | None = None
    cost: int | None = None
    market_value: int | None = None
    txns: list[CasTxn] = field(default_factory=list)


@dataclass
class CasStatement:
    period_from: date | None
    period_to: date | None
    funds: list[CasFund] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)


def is_cas(text: str) -> bool:
    head = text[:3000]
    return bool(CAS_RE.search(head)) and bool(re.search(r"folio", text, re.I))


def _num(s: str, scale: int) -> int:
    """'(1,234.56)' → -123456 with scale 100. Rounds to the given scale."""
    neg = s.startswith("(") or s.startswith("-")
    v = float(s.strip("()").replace(",", "").lstrip("-"))
    return -round(v * scale) if neg else round(v * scale)


def _date(s: str) -> date:
    return datetime.strptime(s.title(), "%d-%b-%Y").date()


def kind_of(desc: str, units: int) -> str:
    d = desc.lower()
    if re.search(r"switch[\s-]*(over\s*)?in|stp[\s-]*in|transfer[\s-]*in", d):
        return "switch_in"
    if re.search(r"switch[\s-]*(over\s*)?out|stp[\s-]*out|transfer[\s-]*out", d):
        return "switch_out"
    if re.search(r"reversal|rejection|rejected|reject", d):
        return "reversal"
    if re.search(r"(dividend|idcw).*(reinvest)|reinvest", d):
        return "dividend_reinvest"
    if re.search(r"(dividend|idcw).*(paid|payout)", d):
        return "dividend_payout"
    if re.search(r"redemption|redeem|withdrawal|repurchase|\bswp\b", d):
        return "redemption"
    if re.search(r"systematic\s+investment|\bsip\b", d):
        return "sip"
    if re.search(r"purchase|investment|subscription|\bnfo\b", d):
        return "purchase"
    return "purchase" if units >= 0 else "redemption"


def _join_wrapped(lines: list[str]) -> list[str]:
    """A transaction whose description wrapped: the dated line has no numbers
    at the end; glue the following lines on until it does."""
    out: list[str] = []
    pending: list[str] = []
    for ln in lines:
        if pending:
            stop = (
                DATE_LEAD_RE.match(ln)
                or AMC_RE.match(ln)
                or FOLIO_RE.search(ln)
                or CLOSING_RE.search(ln)
                or ISIN_RE.search(ln)
                or len(pending) >= 3
            )
            if stop:
                out.extend(pending)  # never completed: keep the lines as they were
                pending = []
            else:
                pending.append(ln)
                joined = " ".join(pending)
                if TXN_RE.match(joined):
                    out.append(joined)
                    pending = []
                continue
        if (
            DATE_LEAD_RE.match(ln)
            and not TXN_RE.match(ln)
            and not TAX_RE.match(ln)
            and "***" not in ln
            and not PERIOD_RE.match(ln)
        ):
            pending = [ln]
        else:
            out.append(ln)
    out.extend(pending)
    return out


def parse_cas(text: str) -> CasStatement:
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.replace("\r", "").split("\n")]
    lines = _join_wrapped([ln for ln in lines if ln])
    period = PERIOD_RE.search(text[:3000])
    st = CasStatement(_date(period.group(1)) if period else None, _date(period.group(2)) if period else None)
    amc = ""
    folio = ""
    fund: CasFund | None = None
    for ln in lines:
        if m := AMC_RE.match(ln):
            amc = m.group(1).strip()
            continue
        if m := FOLIO_RE.search(ln):
            folio = re.sub(r"\s+", "", m.group(1))
            continue
        if m := ISIN_RE.search(ln):
            name = ln[: m.start()]
            name = re.sub(r"^[A-Z0-9]{1,12}-", "", name).strip(" -:")
            reg = REGISTRAR_RE.search(ln)
            fund = CasFund(
                amc=amc,
                folio=folio,
                scheme=name,
                isin=m.group(1).upper(),
                registrar=reg.group(1).upper() if reg else None,
            )
            st.funds.append(fund)
            continue
        if fund is None:
            continue
        if m := OPENING_RE.search(ln):
            fund.opening_units = _num(m.group(1), 1000)
            continue
        if m := CLOSING_RE.search(ln):
            fund.closing_units = _num(m.group(1), 1000)
        if m := NAV_RE.search(ln):
            fund.nav_date, fund.nav = _date(m.group(1)), _num(m.group(2), 10000)
        if m := COST_RE.search(ln):
            fund.cost = _num(m.group(1), 100)
        if m := MARKET_RE.search(ln):
            fund.market_value = _num(m.group(2), 100)
        if CLOSING_RE.search(ln) or NAV_RE.search(ln) or COST_RE.search(ln) or MARKET_RE.search(ln):
            continue
        if m := TXN_RE.match(ln):
            units = _num(m.group(4), 1000)
            fund.txns.append(
                CasTxn(
                    date=_date(m.group(1)),
                    description=m.group(2).strip(),
                    kind=kind_of(m.group(2), units),
                    amount=_num(m.group(3), 100),
                    units=units,
                    nav=abs(_num(m.group(5), 10000)),
                    balance=_num(m.group(6), 1000),
                )
            )
            continue
        if m := TAX_RE.match(ln):
            if m.group(3) and re.search(r"stamp\s*duty", m.group(2), re.I):
                d = _date(m.group(1))
                for t in reversed(fund.txns):
                    if t.date == d and t.amount > 0:
                        t.stamp_duty += abs(_num(m.group(3), 100))
                        break
            continue  # STT / TDS / nominee notes: nothing to record
        if DATE_LEAD_RE.match(ln):
            st.unparsed.append(ln)
    return st


def consistency(st: CasStatement) -> int:
    """Rows whose unit balance follows from the one before (to pick the best text extraction)."""
    ok = 0
    for f in st.funds:
        prev = f.opening_units
        for t in f.txns:
            if abs(prev + t.units - t.balance) <= 1:
                ok += 1
            prev = t.balance
    return ok

"""Read Indian bank / card transaction alert emails into a transaction suggestion.

Typical alerts:
  "Rs.450.00 has been debited from account **1234 to VPA swiggy@icici on 12-11-26."
  "INR 1,299.00 spent on HDFC Bank Card XX5678 at AMAZON PAY on 2026-11-12 10:41:02."
  "Your A/c XX1234 is credited with INR 80,000.00 on 01-Nov-26 by NEFT from ACME CORP."

Best effort: wording differs per bank, so the result is only a pre-fill that you
check before saving. Returns None when no amount or direction can be found.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime

_AMOUNT = re.compile(r"(?:rs\.?|inr|₹)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)
_DEBIT = re.compile(r"\b(debited|spent|withdrawn|paid|purchase|sent|deducted|used\s+for)\b", re.I)
_CREDIT = re.compile(r"\b(credited|received|deposited|refund(?:ed)?|reversed|cashback)\b", re.I)
_LAST4 = re.compile(
    r"(?:a/c|acct|account|card|ac)\s*(?:no\.?|number|ending(?:\s+with)?|ending\s+in)?\s*[:.]?\s*"
    r"(?:[x*]+|\*\*|xx)?\s*([0-9]{4})\b",
    re.I,
)
_VPA = re.compile(r"\bvpa\s+([a-z0-9._-]+)@[a-z0-9.-]+", re.I)
_MERCHANT = re.compile(
    r"\b(?:at|to|towards|for|by|from|info:?)\s+"
    r"([A-Za-z0-9][A-Za-z0-9&'._/*-]*(?:\s+[A-Za-z0-9&'._/*-]+){0,4}?)"
    r"(?=\s+(?:on|via|ref|upi|avl|avbl|at|is|for|using|with|from\s+(?:a/c|acct|account|card))\b|\s+-|[.,;]|\s*$)",
    re.I,
)
_NOT_MERCHANT = re.compile(r"^(?:your|you|a/c|account|card|rs|inr|the|us|bank|customer|xx\d*|\*+\d*)$", re.I)

_MONTHS = {
    m: i
    for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)
}
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b"), "dmy"),
    (re.compile(r"\b(\d{1,2})[-\s]([A-Za-z]{3})[A-Za-z]*[-\s,]+(\d{2,4})\b"), "dMy"),
    (re.compile(r"\b([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b"), "Mdy"),
]
# Payment rails written before the name: "NEFT from ACME CORP" -> "ACME CORP"
_RAIL = re.compile(r"^(?:neft|imps|rtgs|upi|ach|nach|ecs)\b[\s/-]*(?:(?:from|to|by|cr|dr)\b\s*)?", re.I)


@dataclass
class AlertSuggestion:
    type: str  # withdrawal | deposit
    amount: int  # paise
    date: date
    merchant: str | None
    account_last4: str | None


def _to_paise(raw: str) -> int | None:
    try:
        return round(float(raw.replace(",", "")) * 100)
    except ValueError:
        return None


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if n < 100 else n


def _find_date(text: str) -> date | None:
    for rx, kind in _DATE_PATTERNS:
        for m in rx.finditer(text):
            try:
                if kind == "ymd":
                    return date(int(m[1]), int(m[2]), int(m[3]))
                if kind == "dmy":
                    return date(_year(m[3]), int(m[2]), int(m[1]))
                if kind == "Mdy":
                    mon = _MONTHS.get(m[1][:3].lower())
                    if mon:
                        return date(int(m[3]), mon, int(m[2]))
                    continue
                mon = _MONTHS.get(m[2][:3].lower())
                if mon:
                    return date(_year(m[3]), mon, int(m[1]))
            except ValueError:
                continue
    return None


def _clean_merchant(raw: str) -> str | None:
    name = re.sub(r"\s+", " ", raw).strip(" .,-*/")
    name = _RAIL.sub("", name).strip(" .,-*/")
    if not name or _NOT_MERCHANT.match(name) or re.fullmatch(r"[0-9 ./-]+", name):
        return None
    if (name.isupper() or name.islower()) and len(name) > 3:
        name = name.title()
    return name[:80]


def parse_alert(subject: str | None, body: str | None, sent_at: datetime | None) -> AlertSuggestion | None:
    """A suggestion from an alert email, or None when it doesn't look like one."""
    text = " ".join(filter(None, [subject, body]))[:4000]
    text = re.sub(r"\s+", " ", text)
    amount_m = _AMOUNT.search(text)
    if not amount_m:
        return None
    amount = _to_paise(amount_m[1])
    if not amount or amount <= 0:
        return None
    debit, credit = _DEBIT.search(text), _CREDIT.search(text)
    if not debit and not credit:
        return None
    # The first direction word wins ("debited … refund" is a debit).
    kind = "withdrawal" if debit and (not credit or debit.start() < credit.start()) else "deposit"

    last4 = _LAST4.search(text)
    merchant = None
    vpa = _VPA.search(text)
    if vpa:
        merchant = _clean_merchant(vpa[1].replace(".", " ").replace("_", " "))
    if not merchant:
        for m in _MERCHANT.finditer(text[amount_m.start() :] if amount_m else text):
            merchant = _clean_merchant(m[1])
            if merchant:
                break
    when = _find_date(text) or (sent_at.date() if sent_at else date.today())
    return AlertSuggestion(
        type=kind,
        amount=amount,
        date=when,
        merchant=merchant,
        account_last4=last4[1] if last4 else None,
    )

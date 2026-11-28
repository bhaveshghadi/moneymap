"""Which investment a bank payment belongs to: used by "Move past payments here" and by bank
statement import. Careful on purpose — a payment needs the investment's number, a name from
it, or a word for its kind (SIP, LIC, RD, chit …); the instalment amount alone is never enough."""

import re
from dataclasses import dataclass

from .models import Investment

ROUNDING = 100  # paise
# words that say what kind of investment a payment is for
KIND_WORDS = {
    "mf": r"\bsip\b|mutual|\bmf\b|bse ?star|nse ?mf|\bcams\b|kfin|groww|zerodha|coin by|kuvera|paytm money|ach.*\bmf\b",
    "insurance": r"\blic\b|premium|insurance|life ins|policy",
    "rd": r"\brd\b|recurring",
    "post_office": r"post ?office|india post|\bnsc\b|\bkvp\b|\bscss\b|\bmis\b|\bppf\b|sukanya|\bssy\b",
    "retirement": r"\bppf\b|\bnps\b|\bepf\b|sukanya|\bssy\b|pran",
    "chit": r"\bchit",
    "gold": r"\bgold\b|\bsgb\b|augmont|mmtc|safegold|silver",
    "fd": r"\bfd\b|fixed dep|term dep|\btd\b",
    "stocks": r"zerodha|groww|upstox|angel|\bicici ?sec|demat|broking|securities",
    "crypto": r"wazirx|coindcx|coinswitch|binance|crypto",
    "bond": r"\bncds?\b|\bbonds?\b|\bwint\b|wint ?wealth|goldenpi|grip ?invest|indiabonds|\bcoupon|jiraaf|altifi",
}
# words that say money came back
BACK_WORDS = (
    r"redemption|redeem|maturity|matured|repaid|repay|refund|payout|closure|claim|surrender|dividend|idcw|interest"
)
GENERIC = {
    "fund", "funds", "mutual", "direct", "growth", "plan", "regular", "option", "bank", "limited", "ltd", "india",
    "the", "and", "insurance", "life", "corporation", "company", "deposit", "fixed", "recurring", "account",
    "scheme", "post", "office", "index", "flexi", "large", "small", "cap", "mid", "equity", "debt", "hybrid",
    "payout", "reinvestment", "idcw", "dividend", "money", "lent", "chit", "gold", "silver", "jewellery", "other",
}  # fmt: skip


@dataclass
class Hit:
    account_id: int
    why: str
    amount_match: bool
    strong: bool  # number or a name matched (not only a kind word)


def _words(inv: Investment) -> list[str]:
    texts = [inv.institution, inv.person, inv.account.name]
    if inv.fund is not None:
        texts += [inv.fund.scheme, inv.fund.amc]
    out: list[str] = []
    for t in texts:
        for w in re.findall(r"[a-z]{4,}", (t or "").lower()):
            if w not in GENERIC and w not in out:
                out.append(w)
    return out


def score(inv: Investment, text: str, amount: int) -> Hit | None:
    """`amount` in paise, money out of the bank > 0, money back in < 0."""
    if inv.closed_on or (inv.kind == "insurance" and inv.subtype == "term"):
        return None
    low = text.lower()
    digits = re.sub(r"\D", " ", text)
    # the longest digit group of the FD / policy / folio number ("9988776/12" -> 9988776)
    raw = inv.number or (inv.fund.folio if inv.fund else "") or ""
    number = max(re.findall(r"\d+", raw), key=len, default="")
    # its last 4 digits, alone ("XXXX5678") or ending a longer run ("50300012345678")
    by_number = len(number) >= 4 and re.search(rf"(?<!\d)\d*{number[-4:]}(?!\d)", digits) is not None
    name = next((w for w in _words(inv) if re.search(rf"\b{w}", low)), None)
    kind_rx = KIND_WORDS.get(inv.kind)
    if inv.kind == "post_office" and inv.subtype == "rd":
        kind_rx = KIND_WORDS["rd"] + "|" + KIND_WORDS["post_office"]
    by_kind = bool(kind_rx and re.search(kind_rx, low))
    if inv.kind == "lent" and not name:
        return None  # money lent: only the person's name says who it is
    target = inv.instalment
    amount_match = bool(target and abs(abs(amount) - target) <= ROUNDING)
    if amount < 0 and not (
        re.search(BACK_WORDS, low) or inv.kind == "lent" or (inv.kind == "bond" and (name or by_kind))
    ):
        return None  # money in from an investment says what it is (redemption, maturity …)
    strong = by_number or bool(name)
    # a bank's or company's name alone (HDFC, LIC …) is too common: it needs a kind word or the amount too
    # (a bond's issuer is specific enough)
    named = bool(name) and (inv.kind in ("lent", "bond") or by_kind or amount_match)
    if not (by_number or named or (by_kind and amount_match)):
        return None
    why = (
        f"number {number[-4:]} is in the description"
        if by_number
        else f"“{name}” is in the description"
        if name
        else "the amount and the description fit"
    )
    return Hit(inv.account_id, why, amount_match, strong)


def best(investments: list[Investment], text: str, amount: int) -> Hit | None:
    """The single best investment for a payment (None when two fit equally well)."""
    hits = [h for inv in investments if (h := score(inv, text, amount))]
    if not hits:
        return None
    hits.sort(key=lambda h: (h.strong, h.amount_match), reverse=True)
    top = hits[0]
    if len(hits) > 1 and (hits[1].strong, hits[1].amount_match) == (top.strong, top.amount_match):
        return None
    return top

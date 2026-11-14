"""Universal Indian statement parser (bank + credit card).

Generic parser for Indian bank and card statements (shared rules and
test fixtures). Text in, signed paise rows out — no classification.

- Bank statements carry an amount AND a running balance per row: direction
  comes from the sign of the balance change (the most reliable signal).
- Card statements carry one amount per row: direction comes from Cr/Dr markers
  or credit words (payment, refund, reversal, cashback); default is a purchase.
"""

import re
from dataclasses import dataclass, field
from datetime import date

DATE_RE = re.compile(r"\b(\d{2})[/-](\d{2})[/-](\d{2}(?:\d{2})?)\b")
# Money token: comma-grouped (1,80,000.00), decimal (1234.56) or short int (<=6 digits).
MONEY_RE = re.compile(r"\b\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?\b|\b\d+\.\d{1,2}\b|\b\d{1,6}\b")
MONEY_TOKEN_RE = re.compile(r"\d[\d,]*\.\d{1,2}\b|\b\d{1,3}(?:,\d{2,3})+\b")
MAX_PAISE = 200_000_000_00  # ignore single-line "amounts" over ₹2 crore

NON_TXN_RE = re.compile(
    r"\b(b/f|c/f|brought forward|carried forward|opening balance|closing balance|balance forward|market value|"
    r"financial summary|statement summary|account summary|sub[- ]?total|grand total|\btotal\b|reward point|"
    r"credit limit|available (credit|balance|limit)|minimum amount due|total amount due|account related|"
    r"page \d+|statement of account|interest rate|annual percentage)\b",
    re.I,
)
CREDIT_RE = re.compile(r"\b(cr|credit|refund|reversal|reversed|cashback|received|repayment)\b|\(cr\)|\+\s*$", re.I)
DEBIT_RE = re.compile(r"\b(dr|debit)\b|\(dr\)", re.I)
ACCOUNT_HEADER_RE = re.compile(
    r"\b(?:a/?c|acc(?:oun)?t|card)\s*(?:no\.?|number|#)?\s*[:-]?\s*((?:[xX*\d][xX*\d \-]{2,})\d{4})\b", re.I
)
VPA_RE = re.compile(r"\b([a-z0-9._-]{2,}@[a-z]{2,})\b", re.I)
BENEFICIARY_RE = re.compile(r"\b(?:neft|imps|rtgs)\b[^-]*-[^-]+-([A-Z][A-Z .]{2,}?)-", re.I)
CARD_STATEMENT_HEADER_RE = re.compile(r"credit card statement|statement for .{0,40}credit card", re.I)
# A standalone payment-rail line printed BETWEEN dated rows (ICICI) belongs to the next row.
# NFS/VAT/MAT = ATM withdrawals, MMT = IMPS, EBA/TOP/IPS per ICICI's legend.
NARRATION_RE = re.compile(
    r"^(upi|imps|neft|rtgs|ach|nach|enach|ecs|bil|cms|atm|pos|vps|ips|inft?|nfs|vat|mat|mmt|eba|top)[/ ]", re.I
)
ROW_COMPLETE_RE = re.compile(r"(?:\d[\d,]*\.\d{1,2}|\d{1,3}(?:,\d{2,3})+)\s*(?:\(?(?:cr|dr)\)?)?\s*$", re.I)
# Page furniture that must never be glued onto a transaction.
FURNITURE_RE = re.compile(
    r"^(total\s*:|page \d+ of \d+|statement of transactions|date\s+mode\s+particulars|"
    r"date\s+(transaction\s+)?(details|description|narration|particulars)|date\s+ser\.?\s*no|"
    r"legends? for transactions)",
    re.I,
)
# A payee name printed on its own line above its row (ICICI): letters only.
NAME_LINE_RE = re.compile(r"[A-Za-z][A-Za-z .&'()-]{1,60}")
# ...or a UPI display name made from a handle: "ravi123 okicici".
HANDLE_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]{2,40} [A-Za-z]{2,20}")
TOTAL_LINE_RE = re.compile(r"^total\s*:", re.I)
# Card statements: sections after the transactions (EMI tables, offers, terms)
# have dates and amounts of their own. Stop reading at one of these and resume
# at the next transaction table header ("Date SerNo. Transaction Details").
CARD_STOP_RE = re.compile(
    r"^(#\s*international spends|emi\s*/\s*personal loan|earnings$|most important terms|important information|"
    r"great offers|reward points? summary|schedule of charges)",
    re.I,
)
CARD_HEADER_RE = re.compile(r"^date\s+ser\.?\s*no", re.I)
OPENING_RE = re.compile(r"\b(b/f|brought forward|opening balance|balance forward)\b", re.I)


@dataclass
class ParsedTxn:
    date: str  # ISO
    amount: int  # signed paise: − out, + in
    description: str
    raw: str
    balance: int | None = None
    counterparty: str | None = None
    name_hint: str | None = None  # payee name printed on its own line (ICICI)


@dataclass
class ParsedStatement:
    doc_type: str  # bank_statement | card_statement
    account_last4: str | None
    txns: list[ParsedTxn] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)


def amount_to_paise(s: str) -> int:
    return round(float(s.replace(",", "")) * 100)


def iso_date(dd: str, mm: str, yy: str) -> str | None:
    year = int(yy) + 2000 if len(yy) == 2 else int(yy)
    try:
        d = date(year, int(mm), int(dd))
    except ValueError:
        return None
    return d.isoformat() if 2000 <= year <= 2099 else None


def _valid(m: re.Match) -> bool:
    return iso_date(m.group(1), m.group(2), m.group(3)) is not None


def extract_counterparty(desc: str) -> str | None:
    if m := VPA_RE.search(desc):
        return m.group(1)
    if m := BENEFICIARY_RE.search(desc):
        return m.group(1).strip()
    return None


CARD_TITLE_LINE_RE = re.compile(r"^\s*credit card statement\s*$", re.I)
CARD_SUMMARY_WORDS = (
    re.compile(r"minimum amount due", re.I),
    re.compile(r"total amount due", re.I),
    re.compile(r"credit limit", re.I),
)


def is_card_statement(text: str) -> bool:
    """A credit card statement: the title in the first lines, a "CREDIT CARD STATEMENT"
    title line further down page 1 (ICICI prints its summary boxes first), or the
    card summary words (minimum amount due, total amount due, credit limit) together."""
    lines = text.split("\n")
    if CARD_STATEMENT_HEADER_RE.search(" ".join(lines[:8])):
        return True
    if any(CARD_TITLE_LINE_RE.match(ln) for ln in lines[:200]):
        return True
    head = "\n".join(lines[:200])
    return all(rx.search(head) for rx in CARD_SUMMARY_WORDS)


def _header_region(text: str) -> list[str]:
    out = []
    for line in text.replace("\r", "").split("\n")[:80]:
        lead = DATE_RE.search(line.strip()[:12])
        if lead and _valid(lead) and MONEY_TOKEN_RE.search(line):
            break
        out.append(line)
    return out


def _masked_number_line(line: str) -> str | None:
    t = line.strip()
    if not re.fullmatch(r"[\dxX* -]+", t):
        return None
    compact = re.sub(r"[ -]", "", t)
    if len(re.findall(r"[xX*]", compact)) < 4 or not 12 <= len(compact) <= 19:
        return None
    m = re.search(r"(\d{4})$", compact)
    return m.group(1) if m else None


def extract_account_last4(text: str) -> str | None:
    for line in _header_region(text):
        if m := ACCOUNT_HEADER_RE.search(line):
            digits = re.sub(r"\D", "", m.group(1))
            if len(digits) >= 4:
                return digits[-4:]
        if masked := _masked_number_line(line):
            return masked
    return None


def _split_merged(row: str) -> list[str]:
    """Split two transactions printed on one line — only at an interior date
    preceded by a real amount (a txn-date + value-date pair stays one row)."""
    out, start = [], 0
    matches = list(DATE_RE.finditer(row))
    if not matches:
        return [row]
    cursor = matches[0].end()
    for m in matches[1:]:
        if not _valid(m):
            continue
        between = row[cursor : m.start()]
        if re.search(r"\d[\d,]*\.\d{1,2}\b|\b\d{1,3}(?:,\d{2,3})+\b", between):
            out.append(row[start : m.start()].strip())
            start = m.start()
        cursor = m.end()
    out.append(row[start:].strip())
    return [r for r in out if r]


def split_rows(text: str, leading_names: bool = False, card: bool = False) -> list[str]:
    return [row for row, _ in split_rows_hinted(text, leading_names, card)]


def split_rows_hinted(text: str, leading_names: bool = False, card: bool = False) -> list[tuple[str, str | None]]:
    """Rows start at a date. Undated lines continue the previous row, except:
    page furniture / totals (dropped), payment-rail narrations printed between
    rows (belong to the next row), and — with `leading_names`, for bank
    statements like ICICI's — a letters-only payee line printed ABOVE its row,
    which is also returned as that row's name hint."""
    normalized = re.sub(r"[ \t]+", " ", text.replace("\r", ""))
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    rows: list[list] = []  # [text, name_hint]
    narration: list[str] = []
    names: list[str] = []
    last_complete = False
    closed = False  # after a "Total:" line nothing more belongs to the last row
    paused = False  # card statement: inside a non-transaction section
    for line in lines:
        if card:
            if CARD_HEADER_RE.search(line):
                paused, closed = False, True
                continue
            if paused:
                continue
            if CARD_STOP_RE.search(line):
                paused, closed, narration, names = True, True, [], []
                continue
        lead = DATE_RE.search(line[:12])
        if lead and _valid(lead):
            if len(names) > 1:
                # Only the line right above the row is its payee name; letters-only
                # lines before it are the previous row's wrapped tail ("NIONBANK OF I").
                if not closed:
                    rows[-1][0] = f"{rows[-1][0]} {' '.join(names[:-1])}"
                names = names[-1:]
            extra = narration + names
            rows.append([f"{line} {' '.join(extra)}" if extra else line, " ".join(names) or None])
            narration, names = [], []
            last_complete = bool(ROW_COMPLETE_RE.search(line))
            closed = False
        elif rows:
            if TOTAL_LINE_RE.search(line):
                closed, narration, names = True, [], []
                continue
            if OPENING_RE.search(line) and not closed:
                rows[-1][0] = f"{rows[-1][0]} {line}"  # "B/F" split off its date: keep it, it marks the opening row
                continue
            if FURNITURE_RE.search(line) or NON_TXN_RE.search(line):
                continue  # "Page 2 of 3", repeated column headers
            if not MONEY_TOKEN_RE.search(line) and NARRATION_RE.search(line) and last_complete:
                narration.append(line)
            elif leading_names and last_complete and (NAME_LINE_RE.fullmatch(line) or HANDLE_NAME_RE.fullmatch(line)):
                names.append(line)
            elif closed or (card and last_complete):
                # footer text, or (cards) anything below a row that already has its amount
                narration, names = [], []
            else:
                rows[-1][0] = f"{rows[-1][0]} {line}"
                last_complete = last_complete or bool(ROW_COMPLETE_RE.search(line))
    if (narration or names) and rows and not closed:
        rows[-1][0] += " " + " ".join(narration + names)
    out: list[tuple[str, str | None]] = []
    for text_, hint in rows:
        for i, part in enumerate(_split_merged(text_)):
            out.append((part, hint if i == 0 else None))
    return out


def _money_tokens(after_date: str) -> list[str]:
    toks = MONEY_RE.findall(after_date)
    decimal_like = [t for t in toks if "." in t or "," in t]
    return decimal_like or toks


# ICICI net-banking download ("OpTransactionHistory…pdf"): each row is
#   <payee name line>
#   <S No> <DD.MM.YYYY> [cheque no] <amount> <balance>
#   <remarks lines: UPI/…/…>
# with separate Withdrawal / Deposit columns that the text doesn't keep apart.
OP_HISTORY_RE = re.compile(r"statement of transactions in sav\w* account", re.I)
OP_ROW_RE = re.compile(r"^(\d{1,4})\s+(\d{2})\.(\d{2})\.(\d{4})\s+(.*\d)$")
OP_FURNITURE_RE = re.compile(
    r"^(\d{1,3}$|www\.icici|please call from|never share your otp|transaction\s+withdrawal|s no\.|date\s+amount)", re.I
)
OP_END_RE = re.compile(r"^(sincerly|sincerely|team icici|this is a system generated|legends for transactions)", re.I)


def _parse_op_history(text: str, doc_type: str) -> ParsedStatement:
    body: list[str] = []  # from the line above the first row to the end of the table, minus page furniture
    for ln in (re.sub(r"[ \t]+", " ", x).strip() for x in text.replace("\r", "").split("\n")):
        if not ln or (OP_FURNITURE_RE.search(ln) and not OP_ROW_RE.match(ln)):
            continue
        if OP_END_RE.search(ln):
            break
        body.append(ln)
    rows = [i for i, ln in enumerate(body) if OP_ROW_RE.match(ln)]
    txns: list[ParsedTxn] = []
    unparsed: list[str] = []
    prev_balance: int | None = None
    for k, i in enumerate(rows):
        m = OP_ROW_RE.match(body[i])
        # The line right above a row is its payee name (for the first row too,
        # and never a line that belongs to the row before).
        floor = rows[k - 1] if k else -1
        name = body[i - 1] if i - 1 > floor else None
        if name and ("/" in name or NARRATION_RE.search(name)):
            name = None
        # Remarks run until the next row's name line.
        nxt = rows[k + 1] if k + 1 < len(rows) else len(body)
        end = nxt - 1 if k + 1 < len(rows) and nxt - 1 > i and "/" not in body[nxt - 1] else nxt
        remarks = " ".join(body[i + 1 : end])
        d = iso_date(m.group(2), m.group(3), m.group(4))
        toks = MONEY_TOKEN_RE.findall(m.group(5))
        raw = f"{body[i]} {remarks}".strip()
        if not d or len(toks) < 2:
            unparsed.append(raw)
            continue
        magnitude, balance = amount_to_paise(toks[-2]), amount_to_paise(toks[-1])
        if prev_balance is not None:  # direction from the running balance
            signed = magnitude if balance >= prev_balance else -magnitude
        else:  # first row: nothing to compare with — use credit words, else a withdrawal
            words = f"{name or ''} {remarks}"
            signed = magnitude if CREDIT_RE.search(words) and not DEBIT_RE.search(words) else -magnitude
        prev_balance = balance
        if magnitude == 0:
            unparsed.append(raw)
            continue
        txns.append(
            ParsedTxn(
                date=d,
                amount=signed,
                description=remarks or (name or ""),
                raw=raw,
                balance=balance,
                counterparty=extract_counterparty(remarks),
                name_hint=name,
            )
        )
    return ParsedStatement(doc_type=doc_type, account_last4=extract_account_last4(text), txns=txns, unparsed=unparsed)


def parse_statement(text: str, doc_type: str = "bank_statement", opening_balance: int | None = None) -> ParsedStatement:
    if OP_HISTORY_RE.search(text[:600]) and sum(1 for ln in text.splitlines() if OP_ROW_RE.match(ln.strip())) >= 1:
        return _parse_op_history(text, doc_type)
    dated: list[tuple[str, str, list[str], str | None]] = []
    unparsed: list[str] = []
    card = is_card_statement(text) or doc_type == "card_statement"
    for raw, hint in split_rows_hinted(text, leading_names=not card, card=card):
        m = DATE_RE.search(raw)
        d = iso_date(m.group(1), m.group(2), m.group(3)) if m else None
        if m and d and opening_balance is None and not dated and OPENING_RE.search(raw):
            # "01-09-2026 B/F 1,22,950.91" fixes the direction of the first row
            toks = _money_tokens(DATE_RE.sub(" ", raw, count=1))
            if toks:
                opening_balance = amount_to_paise(toks[-1])
        if not m or not d or NON_TXN_RE.search(raw):
            unparsed.append(raw)
            continue
        toks = _money_tokens(DATE_RE.sub(" ", raw, count=1))
        if not toks:
            unparsed.append(raw)
            continue
        dated.append((raw, d, toks, hint))

    multi = sum(1 for _, _, t, _ in dated if len(t) >= 2)
    balance_mode = bool(dated) and multi / len(dated) >= 0.6
    prev_balance = opening_balance
    seen: set[str] = set()
    txns: list[ParsedTxn] = []

    for raw, d, toks, hint in dated:
        balance = None
        credit = bool(CREDIT_RE.search(raw)) and not DEBIT_RE.search(raw)
        if balance_mode and len(toks) >= 2:
            balance = amount_to_paise(toks[-1])
            magnitude = amount_to_paise(toks[-2])
            if prev_balance is not None:
                signed = magnitude if balance >= prev_balance else -magnitude
            else:
                signed = magnitude if credit else -magnitude
            prev_balance = balance
        else:
            magnitude = amount_to_paise(toks[-1])
            signed = magnitude if credit else -magnitude
        if magnitude == 0 or abs(signed) > MAX_PAISE:
            unparsed.append(raw)
            continue

        desc = DATE_RE.sub(" ", raw, count=1)
        for t in toks:
            desc = desc.replace(t, " ", 1)
        desc = re.sub(r"\((?:dr|cr)\)", " ", desc, flags=re.I)
        desc = re.sub(r"(^|\s)(?:dr|cr)(?=\s|$)", " ", desc, flags=re.I)
        desc = re.sub(r"\s+", " ", desc.replace("|", " ")).strip()

        sig = f"{d}|{signed}|{re.sub(r'[^a-z0-9]', '', desc.lower())[:40]}"
        if sig in seen:  # same row repeated in a summary + detail section
            unparsed.append(raw)
            continue
        seen.add(sig)
        if hint and desc.endswith(hint):
            desc = desc[: -len(hint)].strip() or desc
        txns.append(
            ParsedTxn(
                date=d,
                amount=signed,
                description=desc,
                raw=raw,
                balance=balance,
                counterparty=extract_counterparty(raw),
                name_hint=hint,
            )
        )

    return ParsedStatement(
        doc_type="card_statement" if is_card_statement(text) else doc_type,
        account_last4=extract_account_last4(text),
        txns=txns,
        unparsed=unparsed,
    )


def balance_consistency(st: ParsedStatement) -> int:
    """How many rows' running balances add up (previous balance ± amount).
    Used to pick the best of several PDF text extractions."""
    ok = 0
    prev = None
    for t in st.txns:
        if t.balance is None:
            continue
        if prev is not None and abs(t.balance - prev) == abs(t.amount):
            ok += 1
        prev = t.balance
    return ok


def balance_mismatches(st: ParsedStatement) -> int:
    """Rows whose running balance does NOT follow from the previous one."""
    bad = 0
    prev = None
    for t in st.txns:
        if t.balance is None:
            continue
        if prev is not None and abs(t.balance - prev) != abs(t.amount):
            bad += 1
        prev = t.balance
    return bad


def score(st: ParsedStatement) -> tuple[int, int, int]:
    """Best extraction: most balances that add up, then fewest that don't
    (a jumbled text can add stray rows), then most rows."""
    return balance_consistency(st), -balance_mismatches(st), len(st.txns)

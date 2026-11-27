"""Loans whose monthly interest follows the actual days (365-day year), and lender statements
that list each EMI as two lines — the repayment, then the month's interest added (Bandhan's
layout). Every number here is made up."""

from datetime import date

from app.core.dates import add_months
from app.modules.loans.maths import build, calc_emi, period_interest
from app.modules.loans.statement import is_loan_statement, parse_loan_statement

from .test_f14_loan_statements import SOA, _b64
from .test_statement_import import PASSWORD

RS = 100
P, RATE, N = 5_00_000 * RS, 900, 36
TAKEN, FIRST = date(2025, 3, 31), date(2025, 5, 1)
EXTRA = 123 * RS  # 1 day of interest (31 March) the lender adds before EMI 1, as Bandhan does


def test_daily_interest_follows_the_month():
    feb = period_interest(10_00_000 * RS, 900, date(2026, 3, 1), True)  # February: 28 days
    mar = period_interest(10_00_000 * RS, 900, date(2026, 4, 1), True)  # March: 31 days
    assert (feb, mar) == (round(10_00_000 * RS * 0.09 * 28 / 365), round(10_00_000 * RS * 0.09 * 31 / 365))
    assert period_interest(10_00_000 * RS, 900, date(2026, 3, 1), False) == 10_00_000 * RS * 9 // 1200
    # off by default: a schedule without `daily` is exactly the rate/12 one
    emi = calc_emi(P, RATE, N)
    assert build(P, RATE, emi, N, FIRST) == build(P, RATE, emi, N, FIRST, daily=False)


def ledger_lines(emi: int):
    """A made-up statement: header, opening line, then repayment + interest lines per EMI."""
    out = [
        "Welcome Letter",
        "Greetings from Bandhan Bank Limited.",
        "repayment details, payable in equated monthly installments, of your Car loan.",
        "Amortization Schedule",
        "Account Number :   11223344556677",
        "Disbursement Date:   31/03/25",
        f"Account Term:   {N + 1}M",
        "MaturityDate:   01/06/28",
        "Interest Rate:   9",
        f"Amount Requested:   {P // RS}",
        "Date   Activity   Amount   Principal   Balance",
        f"20/04/25   0   0   {(P + EXTRA) // RS}",
    ]
    bal, d = P + EXTRA, FIRST
    for n in range(1, N + 1):
        interest = period_interest(bal, RATE, d, True)
        pay = emi + (EXTRA if n == 1 else 0)
        if n == N or bal + interest <= pay:
            pay = bal  # the last one pays off what's left before that month's interest
            out.append(
                f"{d:%d/%m/%y}   Payoff - Close Account   {pay // RS}   {pay // RS}   {(bal - pay - interest) // RS}"
            )
            out.append(f"{d:%d/%m/%y}   Debit - Capitalize Def Int   {interest // RS}   {interest // RS}   0")
            break
        bal -= pay
        out.append(f"{d:%d/%m/%y}   Repayment of loan   {pay // RS}   {pay // RS}   {bal // RS}")
        bal += interest
        out.append(f"{d:%d/%m/%y}   Debit - Capitalize Def Int   {interest // RS}   {interest // RS}   {bal // RS}")
        d = add_months(FIRST, n)
    return out


EMI = calc_emi(P, RATE, N)


def test_reads_a_two_line_ledger():
    text = "\n".join(ledger_lines(EMI))
    assert is_loan_statement(text)
    st = parse_loan_statement(text, ["Bandhan Bank"], date(2026, 11, 26))
    v = st.values
    assert len(st.schedule) >= 30 and st.schedule[0].date == FIRST
    assert (v["principal"], v["rate"], v["emi"], v["first_emi_date"]) == (P, RATE, EMI, FIRST)
    assert v["interest_basis"] == "days365" and v["lender"] == "Bandhan Bank" and v["kind"] == "car"
    assert v["loan_number"] == "11223344556677"
    assert v["tenure"] == len(st.schedule)  # the schedule's own count, not the "37M" term
    assert v["last_emi_date"] == st.schedule[-1].date
    # left to pay: from the schedule as on the day, not the table's "Principal Balance" header
    done = [r for r in st.schedule if r.date <= date(2026, 11, 26)]
    assert v["outstanding"] == done[-1].balance and v["emis_paid"] == len(done)
    assert st.found == []  # month-length changes are not rate changes
    assert st.check and st.check["matches"], st.check


def test_rate_per_twelve_statements_unchanged():
    """A usual schedule (rate/12 every month) reads exactly as before: no interest basis set."""
    st = parse_loan_statement("\n".join(SOA), ["ICICI Bank"], date(2026, 11, 15))
    assert "interest_basis" not in st.values and st.schedule


def test_update_from_statement_offers_daily_interest(client, bank):
    loan = client.post("/api/loans", json={
        "name": "Car", "kind": "car", "loan_number": "XX6677", "principal": P, "rate": 10, "tenure": N,
        "first_emi_date": "2025-04-01", "pay_from_id": bank["id"],
    }).json()  # fmt: skip
    d = client.post("/api/loans/statement/read", json={
        "filename": "car.pdf", "content_b64": _b64(ledger_lines(EMI)[:60]), "password": PASSWORD,
    }).json()  # fmt: skip
    assert d["match"]["account_id"] == loan["id"], d
    diffs = {x["field"]: x for x in d["match"]["differences"]}
    assert diffs["interest_basis"]["patch"] == {"interest_basis": "days365"}
    assert diffs["rate"]["patch"]["rate"] == 9 and diffs["first_emi_date"]["statement"] == FIRST.isoformat()
    assert diffs["emi"]["statement"] == EMI  # the regular EMI, not the bigger first one
    patch = {}
    for f in ("rate", "first_emi_date", "disbursed_date", "first_interest", "interest_basis", "emi"):
        if f in diffs:
            patch |= diffs[f]["patch"]
    r = client.patch(f"/api/loans/{loan['id']}", json=patch)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["interest_basis"] == "days365" and out["first_interest"] == "days365"
    feb = next(x for x in out["schedule"] if x["date"].endswith("-03-01"))
    mar = next(x for x in out["schedule"] if x["date"].endswith("-04-01") and x["n"] > 1)
    assert feb["interest"] < mar["interest"]  # February is shorter


def test_new_loan_with_daily_interest(client, bank):
    r = client.post("/api/loans", json={
        "name": "Car", "principal": P, "rate": 9, "tenure": N, "first_emi_date": FIRST.isoformat(),
        "interest_basis": "days365",
    })  # fmt: skip
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["interest_basis"] == "days365"
    rows = build(P, RATE, out["emi"], N, FIRST, daily=True)
    assert [x["interest"] for x in out["schedule"][:3]] == [x.interest for x in rows[:3]]

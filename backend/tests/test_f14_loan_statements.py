"""F14 phase 3 — loan statements: read a lender's Statement of Account and / or repayment schedule,
pre-fill a new loan, compare with a loan you have, offer part-payments and rate changes.
All statement text here is made up."""

import base64
from datetime import date

from app.modules.loans.maths import Event, build, build_events, calc_emi, first_emi_interest
from app.modules.loans.statement import is_loan_statement, parse_loan_statement

from .test_statement_import import ICICI_LINES, PASSWORD, add_email, make_pdf

LAKH = 100_000_00
P, RATE, N = 6 * LAKH, 925, 24
FIRST, TAKEN = date(2025, 5, 5), date(2025, 3, 28)
BPI = first_emi_interest(P, RATE, FIRST, TAKEN, "days360")
EMI = calc_emi(P, RATE, N, BPI)


def m(p: int) -> str:
    whole, frac = divmod(p, 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])
    return f"{s}.{frac:02d}"


def schedule_lines(rows, opening=P, numbered=True, fmt="%d-%b-%Y"):
    out, bal = [], opening
    for r in rows:
        lead = f"{r.n} " if numbered else ""
        out.append(f"{lead}{r.date:{fmt}} {m(bal)} {m(r.emi)} {m(r.principal)} {m(r.interest)} {m(r.balance)}")
        bal = r.balance
    return out


ROWS = build(P, RATE, EMI, N, FIRST, first_interest=BPI)
SOA = [
    "ICICI Bank Limited",
    "Statement of Account",
    "Loan Account No : LBMUM00012345678        Product : Car Loan",
    f"Loan Amount : Rs. {m(P)}     Rate of Interest : 9.25% p.a.",
    f"Tenure : {N} Months    EMI Amount : {m(EMI)}",
    "Disbursal Date : 28/03/2025    EMI Start Date : 05/05/2025",
    "Principal Outstanding as on 15/11/2026 : 2,12,345.00",
    "No. of EMIs paid : 19    EMIs Remaining : 5",
    "Transaction Details",
    f"05/06/2025 EMI Received NACH {m(EMI)}",
    "Repayment Schedule",
    "Inst No Due Date Opening Principal EMI Principal Interest Closing Principal",
    *schedule_lines(ROWS),
]


# ---------------------------------------------------------------- reading


def test_reads_statement_of_account_and_schedule():
    text = "\n".join(SOA)
    assert is_loan_statement(text)
    st = parse_loan_statement(text, ["ICICI Bank", "HDFC Bank"], today=date(2026, 11, 20))
    v = st.values
    assert (v["loan_number"], v["lender"], v["kind"]) == ("LBMUM00012345678", "ICICI Bank", "car")
    assert (v["principal"], v["rate"], v["tenure"], v["emi"]) == (P, RATE, N, EMI)
    assert (v["first_emi_date"], v["disbursed_date"]) == (FIRST, TAKEN)
    assert (v["outstanding"], v["emis_paid"], v["statement_date"]) == (2_12_345_00, 19, date(2026, 11, 15))
    assert v["first_interest"] == "days360" and "first_interest" in st.worked_out
    assert len(st.schedule) == N and st.check == {"rows": N, "max_diff": 0, "matches": True}
    assert st.found == []


def test_schedule_alone_fills_everything():
    """No labels: amount, EMI, first EMI, rate, tenure (a schedule that stops part-way) and how
    EMI 1's interest was counted (so the taken-on date) — all from the table."""
    text = "\n".join(["HDFC Bank", "Repayment Schedule", "Due Date EMI Principal Interest Balance",
                      *[f"{r.date:%d/%m/%Y} {m(r.emi)} {m(r.principal)} {m(r.interest)} {m(r.balance)}"
                        for r in ROWS[:12]]])  # fmt: skip
    assert is_loan_statement(text)
    st = parse_loan_statement(text, ["HDFC Bank"], today=date(2025, 11, 20))
    v = st.values
    assert (v["principal"], v["rate"], v["tenure"], v["emi"], v["first_emi_date"]) == (P, RATE, N, EMI, FIRST)
    assert (v["first_interest"], v["disbursed_date"]) == ("days360", TAKEN)
    assert v["emis_paid"] == 7 and v["outstanding"] == ROWS[6].balance  # EMIs dated up to "today"
    assert st.check and st.check["matches"]


def test_labels_in_a_row_with_values_below():
    text = "\n".join([
        "Loan Statement", "Loan A/c No   Loan Amount   ROI   Tenure",
        "HL0099887766   25,00,000.00   8.65%   240", "EMI Amount : 21,931.00", "First EMI Date : 10-Jan-2024",
    ])  # fmt: skip
    st = parse_loan_statement(text, [])
    v = st.values
    assert (v["loan_number"], v["principal"], v["rate"], v["tenure"]) == ("HL0099887766", 25 * LAKH, 865, 240)
    assert (v["emi"], v["first_emi_date"]) == (21_931_00, date(2024, 1, 10))


def test_part_payment_and_rate_change_from_entries_and_schedule():
    events = [Event(date(2025, 9, 20), "prepay", "reduce_tenure", amount=1 * LAKH),
              Event(date(2026, 2, 1), "rate", "reduce_emi", rate_bp=875)]  # fmt: skip
    rows, _ = build_events(P, RATE, EMI, N, FIRST, events, BPI)
    lines, bal = ["Statement of Account", "Loan Account No : LBMUM00012345678", "Rate of Interest : 8.75%"], P
    lines.append("20/09/2025 Part Prepayment Received 1,00,000.00 3,10,000.00")
    lines.append("20/09/2025 Part Prepayment Charges 2,000.00")
    for r in rows:  # the opening balance after the part-payment is lower than the last closing
        if r.date == date(2025, 10, 5):
            bal -= 1 * LAKH
        lines.append(f"{r.n} {r.date:%d-%m-%Y} {m(bal)} {m(r.emi)} {m(r.principal)} {m(r.interest)} {m(r.balance)}")
        bal = r.balance
    st = parse_loan_statement("\n".join(lines), [])
    kinds = [(f.kind, f.date, f.amount, f.rate_bp, f.mode, f.source) for f in st.found]
    assert kinds == [
        ("prepay", date(2025, 9, 20), 1 * LAKH, None, "reduce_tenure", "statement"),  # the entry, not a schedule twin
        ("rate", date(2026, 1, 6), None, 875, "reduce_emi", "schedule"),  # before the 5 Feb EMI
    ]
    assert st.values["rate"] == RATE  # the start rate from the schedule; today's is 8.75 (label)


def test_key_facts_statement():
    """The RBI's Key Facts Statement given at sanction: amounts after "(in Rupees) (SI no. 2 …)"
    notes, numbered items, "Upto 24 EMI", fees deducted from the disbursed amount, prose."""
    p, rate, n = 5 * LAKH, 1125, 48
    first, sanction = date(2027, 3, 10), date(2027, 1, 29)  # 40 days
    emi = calc_emi(p, rate, n, first_emi_interest(p, rate, first, sanction, "days365"))
    text = "\n".join([
        "Key Facts Statement",
        "Part 1 (Interest rate and fees/charges)",
        "1. Loan Proposal/ Account No. 99001122334 Type of Loan: Personal Loan",
        f"2. Sanctioned Loan Amount (in Rupees) ₹{p // 100}",
        "3. Disbursal schedule:",
        "100% upfront",
        "4. Loan term (year/months/days)",
        "5. Installments details",
        "Type of", "installments", "Number of", "EPIs",
        "EPI (₹) Commencement of repayment , post", "sanction",
        f"Monthly {n} ₹{emi // 100} 40 Days",
        "6. Interest rate (%) and type (fixed, floating, or hybrid) 11.25 % fixed",
        "8. Fee/Charges (Deducted from loan amount)",
        "i. Processing fees One-time ₹5999",
        "9. Annual Percentage Rate (APR) (%) 11.62 %",
        "Post 1 EMI & Upto 24 EMI repayment 3% on amount being prepaid",
        "Equated Monthly Instalments (EMI) based Personal Loans dated August 18, 2023.",
        "Annex B",
        f"1. Sanctioned Loan amount (in Rupees) (SI no. 2 of the KFS template- Part 1) {p // 100}",
        f"2. Loan Term (in year/months/days) (SI no.4 of the KFS template- Part 1) {n} months",
        "4. Rate of Interest (SI No. 6 of the KFS template- Part 1) 11.25 %",
        "7. a. Disbursed amount (1-6) (in rupees) for APR calculation (excluding stamp duty charges)",
        "b. Net disbursed amount (in Rupees) **",
        f"{(p - 599900) // 100}",
        f"11. Due date of payment of instalment and interest {first:%d/%m/%Y}",
        "*For upfront fees/charges which are deducted from disbursement amount, please refer Annex A, Sr no 8",
        f"₹ {p // 100}(loan amount)+₹ 1,23,456(interest charges)) mentioned under (8)",
    ])  # fmt: skip
    assert is_loan_statement(text)
    st = parse_loan_statement(text, ["ICICI Bank"], date(2027, 2, 1))
    v = st.values
    assert v["loan_number"] == "99001122334" and v["kind"] == "personal"
    assert (v["principal"], v["tenure"], v["rate"], v["emi"]) == (p, n, rate, emi)
    assert v["first_emi_date"] == first
    # the EMI is above the formula's: EMI 1 carries 40 days' interest from sanction
    assert (v["first_interest"], v["disbursed_date"]) == ("days365", sanction)
    assert {"first_interest", "disbursed_date"} <= st.worked_out


def test_bank_and_card_statements_are_not_loans():
    from .test_f17_card_statements import ICICI_CARD_LINES

    assert not is_loan_statement("\n".join(ICICI_LINES))
    assert not is_loan_statement("\n".join(ICICI_CARD_LINES))
    lines = [ln for ln in ICICI_CARD_LINES if ln != "CREDIT CARD STATEMENT" and "Card Number" not in ln]
    assert not is_loan_statement("\n".join(ln for ln in lines if not ln.startswith(("Total", "Minimum", "Credit"))))


# ---------------------------------------------------------------- API


def _b64(lines, password=PASSWORD):
    return base64.b64encode(make_pdf(lines, password)).decode()


SHORT = SOA[:10] + SOA[10:13] + schedule_lines(ROWS[:12])  # fits on one test PDF page


def test_upload_password_and_new_loan_fields(client):
    body = {"filename": "loan.pdf", "content_b64": _b64(SHORT)}
    r = client.post("/api/loans/statement/read", json=body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "password_required"
    r = client.post("/api/loans/statement/read", json={**body, "password": PASSWORD, "remember_password": True})
    assert r.status_code == 200, r.text
    d = r.json()
    f = {k: (x["value"], x["source"]) for k, x in d["fields"].items()}
    assert f["principal"] == (P, "statement") and f["rate"] == (9.25, "statement")
    assert f["first_interest"] == ("days360", "worked_out") and f["first_emi_date"] == ("2025-05-05", "statement")
    assert d["match"] is None and d["check"]["matches"] and d["schedule_rows"] == 12
    # read again by reference: the remembered password opens it
    again = client.post("/api/loans/statement/read", json={"file_ref": d["file_ref"]})
    assert again.status_code == 200 and again.json()["fields"]["emi"]["value"] == EMI


def test_not_a_loan_statement(client):
    r = client.post("/api/loans/statement/read", json={"filename": "x.pdf", "content_b64": _b64(ICICI_LINES, None)})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_loan"


def test_bank_upload_and_inbox_hand_over_to_loans(client):
    r = client.post("/api/statements/upload", json={"filename": "l.pdf", "content_b64": _b64(SHORT),
                                                    "password": PASSWORD})  # fmt: skip
    det = r.json()["detail"]
    assert r.status_code == 422 and det["code"] == "loan_statement" and det["file_ref"]
    # the password just used opens it once more without asking
    assert client.post("/api/loans/statement/read", json={"file_ref": det["file_ref"]}).status_code == 200
    att = add_email(SHORT, mid="loan1", sender="Loans <loans@icici.bank.in>")
    r = client.post("/api/statements", json={"attachment_id": att, "password": PASSWORD})
    assert r.status_code == 422 and r.json()["detail"] == {
        "code": "loan_statement",
        "message": "This is a loan statement — opening it in Loans.",
        "attachment_id": att,
        "file_ref": r.json()["detail"]["file_ref"],
    }
    r = client.post("/api/loans/statement/read", json={"attachment_id": att, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["attachment_id"] == att


def test_existing_loan_differences_and_part_payment(client):
    bank = client.post("/api/accounts", json={"name": "Savings", "type": "asset", "opening_balance": 50 * LAKH}).json()
    loan = client.post("/api/loans", json={
        "name": "Car", "kind": "car", "loan_number": "XX5678", "principal": P, "rate": 9.5, "tenure": N,
        "first_emi_date": FIRST.isoformat(), "start": "existing", "paid_before": 3, "pay_from_id": bank["id"],
    }).json()  # fmt: skip
    pay = client.post("/api/transactions", json={"type": "withdrawal", "date": "2025-09-20", "amount": 1 * LAKH,
                                                 "description": "ICICI loan part payment", "source_id": bank["id"],
                                                 "destination_name": "ICICI Bank"}).json()  # fmt: skip
    lines = [*SHORT[:9], "20/09/2025 Part Prepayment Received 1,00,000.00 3,10,000.00", *SHORT[9:]]
    d = client.post("/api/loans/statement/read", json={"filename": "l.pdf", "content_b64": _b64(lines),
                                                       "password": PASSWORD}).json()  # fmt: skip
    assert d["match"]["account_id"] == loan["id"]  # same loan number (last digits)
    diffs = {x["field"]: x for x in d["match"]["differences"]}
    assert diffs["lender"]["patch"] == {"lender": "ICICI Bank"}
    assert diffs["rate"]["patch"] == {"rate": 9.25, "emi": EMI}  # start rate from the schedule; keep the lender's EMI
    assert diffs["disbursed_date"]["patch"] == {"disbursed_date": "2025-03-28"}
    assert diffs["first_interest"]["patch"]["first_interest"] == "days360"
    assert diffs["emis_paid"]["patch"] == {"paid_before": 19}
    (ev,) = d["events"]
    assert (ev["kind"], ev["amount"], ev["transaction_id"], ev["already_recorded"]) == (
        "prepay",
        1 * LAKH,
        pay["id"],
        False,
    )
    # apply what was ticked through the usual endpoints
    patch = {**diffs["rate"]["patch"], **diffs["disbursed_date"]["patch"], **diffs["first_interest"]["patch"]}
    assert client.patch(f"/api/loans/{loan['id']}", json=patch).status_code == 200
    r = client.post(f"/api/loans/{loan['id']}/prepay", json={"date": ev["date"], "amount": ev["amount"],
                                                             "transaction_id": ev["transaction_id"]})  # fmt: skip
    assert r.status_code == 200, r.text
    d = client.post("/api/loans/statement/read", json={"file_ref": d["file_ref"], "password": PASSWORD}).json()
    fields = {x["field"] for x in d["match"]["differences"]}
    assert not fields & {"rate", "disbursed_date", "first_interest"}
    assert d["events"][0]["already_recorded"] is True


def test_emi_only_loan_gets_the_lenders_split(client):
    """A loan saved as "EMI only" (no rate) can't split EMIs; the schedule turns it into the lender's."""
    loan = client.post("/api/loans", json={"name": "Car", "loan_number": "XX5678", "method": "emi_only",
                                           "principal": P, "emi": EMI, "tenure": N,
                                           "first_emi_date": FIRST.isoformat()}).json()  # fmt: skip
    d = client.post("/api/loans/statement/read", json={"filename": "l.pdf", "content_b64": _b64(SHORT),
                                                       "password": PASSWORD}).json()  # fmt: skip
    assert d["match"]["account_id"] == loan["id"]
    diffs = {x["field"]: x for x in d["match"]["differences"]}
    assert diffs["method"]["current"] == "emi_only" and diffs["method"]["statement"] == "reducing"
    assert diffs["method"]["patch"] == {"method": "reducing", "rate": 9.25, "emi": EMI,
                                        "first_interest": "days360", "disbursed_date": "2025-03-28"}  # fmt: skip
    r = client.patch(f"/api/loans/{loan['id']}", json=diffs["method"]["patch"])
    assert r.status_code == 200, r.text
    first = r.json()["schedule"][0]
    assert (first["principal"], first["interest"]) == (ROWS[0].principal, ROWS[0].interest)
    d = client.post("/api/loans/statement/read", json={"file_ref": d["file_ref"], "password": PASSWORD}).json()
    assert "method" not in {x["field"] for x in d["match"]["differences"]}


def test_part_payment_without_a_payment(client):
    loan = client.post("/api/loans", json={"name": "Old", "principal": P, "rate": 9.25, "tenure": N,
                                           "first_emi_date": FIRST.isoformat()}).json()  # fmt: skip
    r = client.post(f"/api/loans/{loan['id']}/prepay", json={"date": "2025-09-20", "amount": 1 * LAKH,
                                                             "record_payment": False})  # fmt: skip
    assert r.status_code == 200, r.text
    (ev,) = r.json()["events"]
    assert ev["amount"] == 1 * LAKH and ev["txn_id"] is None
    assert client.get("/api/transactions").json()["items"] == []
    assert client.delete(f"/api/loans/{loan['id']}/events/{ev['id']}").status_code == 200

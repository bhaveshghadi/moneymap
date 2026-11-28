"""Bank statements laid out as date, value date, description, amount and Dr / Cr with no balance
column (Bandhan Bank's savings account statement). Every name and number here is made up."""

from app.modules.statements.parser import _any_date, parse_statement, score

from .test_statement_import import make_pdf

LINES = [
    "Current and Savings Account Statement",
    "Account Number   10000000001234",
    "Statement period   01 Aug 2026 to 30 Nov 2026",
    "Transaction Date   Value Date   Description   Amount   Dr / Cr",
    "12Nov 2026   12Nov 2026   GST 1820-GST   INR36.00   Dr",
    "12Nov 2026   12Nov 2026   Debit Card Annual Fees exclusive of GST -   INR200.00   Dr",
    "XX9999",
    "01Nov 2026   01Nov 2026   WTHDRL LOAN EMI 70000000000001 -   INR12,719.00   Dr",
    "A SAMPLE PERSON Drawdown",
    "From CASA.",
    "01Nov 2026   01Nov 2026   UPI/CR/C100000000001/A SAMPLE   INR13,000.00   Cr",
    "PERSON/okic/sample@okexample/UPI/",
    "30Sep 2026   30Sep 2026   CASA Credit Interest Capitalized   INR23.00   Cr",
    "Transaction Date   Value Date   Description   Amount   Dr / Cr",  # the header again on page 2
    "01Sep 2026   01Sep 2026   WTHDRL LOAN EMI 70000000000001 -   INR1,12,719.50   Dr",
    "Statement generated on   2026-11-28 13:59:52 IST",
    "Please find the Details of Complimentary Insurance Cover on your Debit Card",
    "Up to INR 2 lakh",
]


def test_reads_dr_cr_rows():
    st = parse_statement("\n".join(LINES), "bank_statement")
    assert st.account_last4 == "1234" and st.unparsed == []
    got = [(t.date, t.amount) for t in st.txns]
    assert got == [
        ("2026-11-12", -3_600),
        ("2026-11-12", -20_000),
        ("2026-11-01", -1_271_900),
        ("2026-11-01", 1_300_000),
        ("2026-09-30", 2_300),
        ("2026-09-01", -11_271_950),
    ]
    assert st.txns[2].description == "WTHDRL LOAN EMI 70000000000001 A SAMPLE PERSON Drawdown From CASA."
    assert st.txns[1].description.endswith("exclusive of GST XX9999")


def test_upload_reads_rows(client):
    acct = client.post("/api/accounts", json={
        "name": "Savings", "type": "asset", "account_number": "XXXX1234", "opening_balance": 0,
    }).json()  # fmt: skip
    import base64

    body = {"filename": "stmt.pdf", "content_b64": base64.b64encode(make_pdf(LINES, None)).decode()}
    r = client.post("/api/statements/upload", json=body)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["account_id"] == acct["id"] and len(d["rows"]) == 6
    assert client.delete(f"/api/statements/{d['id']}").status_code == 204  # the uploaded PDF goes with it


ESTATEMENT = [
    "Statement of Account for the month of August, 2026",
    "Account Number: 10000000001234",
    "Date   Effective Date   Cheque/Reference No   TransactionDetail   Debit   Credit   Balance",
    "01/08/2026 01/08/2026   UPI/CR/C100000000001/A SAMPLE/okic/sam   0.00 13000.00 15842.00",
    "ple@okexample/UPI/ICI0000",
    "01/08/2026 01/08/2026   WTHDRL LOAN EMI 70000000000001-A SAMPLE   12719.00   0.00   3123.00",
    "PERSON Drawdown From CASA.",
    "31/08/2026 31/08/2026   UPI/CR/C100000000002/A SAMPLE/okic/sam   0.00 13000.00 16123.00",
    "Opening   No of Debit   Debit transaction   No of Credit   Credit transaction",
    "2026-08-01 To 2026-08- 2842.00   1.00   12719.00   2.00   26000.00   16123.00",
]


def test_reads_debit_credit_balance_rows():
    st = parse_statement("\n".join(ESTATEMENT), "bank_statement")
    assert [(t.date, t.amount, t.balance) for t in st.txns] == [
        ("2026-08-01", 1_300_000, 1_584_200),
        ("2026-08-01", -1_271_900, 312_300),
        ("2026-08-31", 1_300_000, 1_612_300),
    ]
    assert st.txns[1].description == "WTHDRL LOAN EMI 70000000000001-A SAMPLE PERSON Drawdown From CASA."
    assert st.unparsed == []


def test_duplicate_found_after_editing_is_left_out(client):
    """The account digits didn't match, you set the row as a transfer from ICICI, then chose the
    account: the ICICI -> Bandhan transfer is already recorded, so the row is left out."""
    import base64

    icici = client.post("/api/accounts", json={"name": "ICICI", "type": "asset", "opening_balance": 10_000_000}).json()
    bandhan = client.post("/api/accounts", json={
        "name": "Bandhan", "type": "asset", "account_number": "XXXX9999", "opening_balance": 284_200,
    }).json()  # fmt: skip
    client.post("/api/transactions", json={
        "type": "transfer", "date": "2026-08-01", "amount": 1_300_000, "description": "UPI to Bandhan",
        "source_id": icici["id"], "destination_id": bandhan["id"],
    })  # fmt: skip
    body = {"filename": "aug.pdf", "content_b64": base64.b64encode(make_pdf(ESTATEMENT, None)).decode()}
    d = client.post("/api/statements/upload", json=body).json()
    assert d["account_id"] is None  # 1234 isn't any account's number
    row = next(r for r in d["rows"] if r["date"] == "2026-08-01" and r["amount"] > 0)
    base = f"/api/statements/{d['id']}"
    client.patch(f"{base}/rows/{row['id']}", json={"kind": "transfer", "transfer_account_id": icici["id"]})
    d = client.patch(base, json={"account_id": bandhan["id"]}).json()
    row = next(r for r in d["rows"] if r["id"] == row["id"])
    assert row["status"] == "duplicate" and row["include"] is False

    # ticked in on purpose after seeing it: it stays in
    client.patch(f"{base}/rows/{row['id']}", json={"include": True})
    d = client.post(f"{base}/reparse").json()
    assert next(r for r in d["rows"] if r["date"] == "2026-08-01" and r["amount"] > 0)["include"] is True
    assert client.delete(base).status_code == 204


WITH_BALANCE = [
    "Current and Savings Account Statement",
    "Account Number   10000000001234",
    "Statement period   From 01 Nov 2026 to 28 Nov 2026",
    "Transaction Date   Value Date   Description   Amount   Dr / Cr   Balance",
    "November12, 2026 November12, 2026 GST 1820-GST   INR36.00   Dr   INR3,753.00",
    "November12, 2026 November12, 2026 Debit Card Annual Fees   INR200.00   Dr   INR3,789.00",
    "exclusive of GST - XX9999",
    "November01, 2026 November01, 2026 WTHDRL LOAN EMI   INR12,719.00   Dr   INR3,989.00",
    "70000000000001 -A SAMPLE",
    "PERSON Drawdown",
    "From CASA.",
    "November01, 2026 November01, 2026 UPI/CR/C100000000001/   INR13,000.00   Cr   INR16,708.00",
    "A SAMPLE/okic/",
    "sample@okexample/UPI/",
    "ICI0000",
    "Statement Summary",
    "Opening Balance   Total Credits   Total Debits   Closing Balance",
    "INR3,708.00   INR13,000.00   INR12,955.00   INR3,753.00",
]


def test_reads_dr_cr_with_balance_and_month_first_dates():
    st = parse_statement("\n".join(WITH_BALANCE), "bank_statement")
    assert [(t.date, t.amount, t.balance) for t in st.txns] == [
        ("2026-11-12", -3_600, 375_300),
        ("2026-11-12", -20_000, 378_900),
        ("2026-11-01", -1_271_900, 398_900),
        ("2026-11-01", 1_300_000, 1_670_800),
    ]
    assert st.txns[2].description == "WTHDRL LOAN EMI 70000000000001 -A SAMPLE PERSON Drawdown From CASA."
    assert st.unparsed == []
    assert score(st) == (3, 0, 4, 0)  # newest first: every balance still adds up


def test_other_date_forms():
    assert [_any_date(s) for s in ("12Nov 2026", "12 November, 2026", "Nov 12, 2026", "12/11/2026", "31Feb 2026")] == [
        "2026-11-12", "2026-11-12", "2026-11-12", "2026-11-12", None,
    ]  # fmt: skip

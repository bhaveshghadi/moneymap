"""Card statement import: into the card account, payments linked to the bank side,
fees / refunds / EMI rows, the statement's own figures, and converting old
card-bill expenses into transfers."""

from datetime import date

from app.modules.statements.card_summary import parse_card_summary

from .helpers import spend
from .test_statement_import import ICICI_LINES, add_email, cat

CARD_LINES = [
    "HDFC Bank Credit Card Statement",
    "Card No: XXXX XXXX XXXX 1111",
    "Statement Date : 12/11/2026",
    "Payment Due Date : 02/12/2026",
    "Total Amount Due : 13,040.00",
    "Minimum Amount Due : 652.00",
    "Previous Balance : 16,500.00",
    "Date Transaction Details Amount",
    "15/10/2026 AMAZON PAY INDIA 3,200.00",
    "20/10/2026 SWIGGY BANGALORE 450.00",
    "28/10/2026 PAYMENT RECEIVED THANK YOU 16,500.00 Cr",
    "01/11/2026 FLIPKART REFUND 200.00 Cr",
    "05/11/2026 LATE PAYMENT FEE 500.00",
    "05/11/2026 IGST ON LATE FEE 90.00",
    "08/11/2026 CROMA SMART EMI CONVERSION 9,000.00",
]


def _bank(client):
    return client.post(
        "/api/accounts",
        json={"name": "HDFC Savings", "type": "asset", "account_number": "XXXX2840", "opening_balance": 10_000_000},
    ).json()


def _card(client, last4="1111", **extra):
    body = {"name": "HDFC Millennia", "last4": last4, "statement_day": 12, "due_mode": "days_after", "due_value": 20,
            "opening_owed": 1_650_000, "opening_date": "2026-10-12", **extra}
    r = client.post("/api/cards", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _rows(detail):
    return {r["description"].split()[0]: r for r in detail["rows"]}


# ---------------------------------------------------------------- summary box


def test_summary_box_layouts():
    s = parse_card_summary("\n".join(CARD_LINES))
    assert (s.statement_date, s.due_date, s.total_due, s.min_due, s.previous_balance) == (
        date(2026, 11, 12), date(2026, 12, 2), 1_304_000, 65_200, 1_650_000
    )
    table = "Credit Card Statement\nStatement Date   Payment Due Date   Total Dues   Minimum Amount Due\n" \
            "12/11/2026       02/12/2026         13,000.00    650.00\nStatement Period : 13 Oct 2026 to 12 Nov 2026"
    s = parse_card_summary(table)
    assert (s.statement_date, s.period_start, s.due_date, s.total_due, s.min_due) == (
        date(2026, 11, 12), date(2026, 10, 13), date(2026, 12, 2), 1_300_000, 65_000
    )
    stacked = "Credit Card Statement\nTotal Amount Due\n₹13,000.00\nMinimum Amount Due\n₹650.00\nPayment Due Date\n2 Dec 2026"
    s = parse_card_summary(stacked)
    assert (s.total_due, s.min_due, s.due_date, s.statement_date) == (1_300_000, 65_000, date(2026, 12, 2), None)


# ---------------------------------------------------------------- card statement


def test_card_statement_end_to_end(client):
    bank = _bank(client)
    card = _card(client)
    bill_cat = client.post("/api/categories", json={"name": "Credit Card Bill", "kind": "expense"}).json()["id"]
    # the payment already recorded on the bank side as an expense (e.g. from the bank statement)
    cred = spend(client, bank, 1_650_000, payee="CRED Club", desc="UPI/CRED Club/cred@axisb/payment",
                 date="2026-10-27", category_id=bill_cat)

    att = add_email(CARD_LINES, mid="card1", sender="HDFC Bank <alerts@hdfcbank.net>")
    r = client.post("/api/statements", json={"attachment_id": att, "password": "test-pdf-pass"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert (d["doc_type"], d["account_id"], d["account_suggested"]) == ("card_statement", card["id"], True)
    f = d["figures"]
    assert (f["statement_date"], f["due_date"], f["total_due"], f["min_due"], f["previous_balance"]) == (
        "2026-11-12", "2026-12-02", 1_304_000, 65_200, 1_650_000
    )
    assert (f["debits"], f["credits"], f["adds_up"], f["difference"]) == (1_324_000, 1_670_000, True, 0)

    rows = _rows(d)
    assert rows["AMAZON"]["kind"] == "expense"
    pay = rows["PAYMENT"]
    assert (pay["kind"], pay["status"], pay["link_txn_id"], pay["transfer_account_id"]) == (
        "transfer", "link", cred["id"], bank["id"]
    )
    assert (rows["FLIPKART"]["kind"], rows["FLIPKART"]["category_id"]) == ("income", cat(client, "Refund"))
    fees = cat(client, "Card Fees & Interest")
    assert rows["LATE"]["category_id"] == fees and rows["IGST"]["category_id"] == fees
    assert rows["CROMA"]["flag"] == "emi"

    base = f"/api/statements/{d['id']}/rows"
    for key in ("AMAZON", "SWIGGY", "CROMA"):
        assert client.patch(f"{base}/{rows[key]['id']}", json={"leave_uncategorised": True}).status_code == 200
    res = client.post(f"/api/statements/{d['id']}/import").json()
    assert res["imported"] == 7

    # the CRED expense became the bank -> card transfer (not a second entry)
    t = client.get(f"/api/transactions/{cred['id']}").json()
    assert (t["type"], t["destination"]["id"], t["category"]) == ("transfer", card["id"], None)
    transfers = client.get("/api/transactions", params={"type": "transfer"}).json()
    assert transfers["total"] == 1

    c = client.get(f"/api/cards/{card['id']}").json()
    assert c["owed"] == 1_304_000  # matches the statement's total due
    nov = next(x for x in c["cycles"] if x["statement_date"] == "2026-11-12")
    assert (nov["official"], nov["total_due"], nov["min_due"], nov["due_date"]) == (True, 1_304_000, 65_200, "2026-12-02")


def test_payment_already_imported_is_a_duplicate(client):
    bank = _bank(client)
    card = _card(client)
    client.post("/api/transactions", json={"type": "transfer", "date": "2026-10-28", "amount": 1_650_000,
                                           "description": "Card bill", "source_id": bank["id"],
                                           "destination_id": card["id"]})
    att = add_email(CARD_LINES, mid="card2", sender="HDFC Bank <alerts@hdfcbank.net>")
    d = client.post("/api/statements", json={"attachment_id": att, "password": "test-pdf-pass"}).json()
    pay = _rows(d)["PAYMENT"]
    assert pay["status"] == "duplicate" and pay["link_txn_id"] is None


def test_unlinking_imports_a_new_transfer(client):
    bank = _bank(client)
    _card(client)
    cred = spend(client, bank, 1_650_000, payee="CRED Club", desc="CRED payment", date="2026-10-27")
    att = add_email(CARD_LINES, mid="card3", sender="HDFC Bank <alerts@hdfcbank.net>")
    d = client.post("/api/statements", json={"attachment_id": att, "password": "test-pdf-pass"}).json()
    pay = _rows(d)["PAYMENT"]
    assert pay["link_txn_id"] == cred["id"]
    r = client.patch(f"/api/statements/{d['id']}/rows/{pay['id']}", json={"link_txn_id": None}).json()
    assert (r["link_txn_id"], r["status"]) == (None, "ready")
    assert client.patch(f"/api/statements/{d['id']}/rows/{pay['id']}", json={"link_txn_id": 5}).status_code == 422


def test_bank_statement_card_payment_suggests_the_card(client):
    client.post("/api/accounts", json={"name": "ICICI Savings", "type": "asset", "account_number": "XXXX2840",
                                       "opening_balance": 5_000_000})
    card = _card(client, last4="9012", name="ICICI Amazon Pay")
    _card(client, last4="1111", name="Other card")
    att = add_email(ICICI_LINES, mid="bank1")
    d = client.post("/api/statements", json={"attachment_id": att, "password": "test-pdf-pass"}).json()
    row = next(r for r in d["rows"] if "CC PAYMENT" in r["description"])
    assert (row["kind"], row["transfer_account_id"], row["status"]) == ("transfer", card["id"], "ready")
    assert d["figures"] is None  # not a card statement


def test_convert_old_card_bill_expenses(client):
    bank = _bank(client)
    card = _card(client)
    bill_cat = client.post("/api/categories", json={"name": "Credit Card Bill", "kind": "expense"}).json()["id"]
    a = spend(client, bank, 6_039_441, payee="CRED Club", desc="UPI/CRED Club/payment on", date="2026-10-03",
              category_id=bill_cat)
    b = spend(client, bank, 2_307_343, payee="Someone", desc="card bill", date="2026-10-03", category_id=bill_cat)
    spend(client, bank, 50_000, payee="Swiggy", desc="Lunch", date="2026-10-04")  # not a card payment
    items = client.get("/api/cards/convertible").json()
    assert {i["transaction_id"] for i in items} == {a["id"], b["id"]}
    assert all(i["suggested_card_id"] == card["id"] for i in items)
    res = client.post("/api/cards/convert", json={"items": [{"transaction_id": i["transaction_id"],
                                                              "card_id": card["id"]} for i in items]}).json()
    assert res["converted"] == 2 and res["empty_categories"] == [{"id": bill_cat, "name": "Credit Card Bill"}]
    assert client.get("/api/cards/convertible").json() == []
    assert client.get("/api/transactions", params={"type": "withdrawal"}).json()["sum_out"] == 50_000
    bad = client.post("/api/cards/convert", json={"items": [{"transaction_id": a["id"], "card_id": card["id"]}]})
    assert bad.status_code == 422  # already a transfer


def test_link_to_an_expense_converted_meanwhile_is_not_added_twice(client):
    bank = _bank(client)
    card = _card(client)
    cred = spend(client, bank, 1_650_000, payee="CRED Club", desc="CRED payment", date="2026-10-27")
    att = add_email(CARD_LINES, mid="card4", sender="HDFC Bank <alerts@hdfcbank.net>")
    d = client.post("/api/statements", json={"attachment_id": att, "password": "test-pdf-pass"}).json()
    assert _rows(d)["PAYMENT"]["link_txn_id"] == cred["id"]
    client.post("/api/cards/convert", json={"items": [{"transaction_id": cred["id"], "card_id": card["id"]}]})
    for r in d["rows"]:
        if r["status"] == "needs_category":
            client.patch(f"/api/statements/{d['id']}/rows/{r['id']}", json={"leave_uncategorised": True})
    client.post(f"/api/statements/{d['id']}/import")
    assert client.get("/api/transactions", params={"type": "transfer"}).json()["total"] == 1


# ICICI Amazon Pay layout: summary boxes first, the "CREDIT CARD STATEMENT" title further
# down, other text right after a row, and an EMI table (with its own dates) at the end.
ICICI_CARD_LINES = [
    "PAYMENT DUE DATE",
    "STATEMENT DATE",
    "STATEMENT SUMMARY",
    "Total Amount due",
    "Minimum Amount due",
    "Card Number 4315XXXXXXXX1111",
    "Date SerNo. Transaction Details Reward Points Intl.# amount Amount (in`)",
    "18/09/2026 14195922942 AMAZON PAY IN UTILITY BANGALORE IN 139 6,990.00",
    "01/10/2026 14275768985 SWIGGY FOOD BANGALORE IN 10 1,074.00",
    "Credit Limit (Including cash) Available Credit (Including cash) Cash Limit Available Cash",
    "3,00,000.00 84,594.06 30,000.00 15,000.00",
    "ICICI Bank Credit Card GST Number: 27AAACI1195H3ZK",
    "HSN Code: 997113 Credit Granting Services including",
    "Statement period : September 19, 2026 to October 18, 2026",
    "CREDIT CARD STATEMENT",
    "03/10/2026 14280290041 BBPS Payment received 0 23,073.43 CR",
    "17/10/2026 14388317738 RAZ*NBB Enterprise Tiruppur TN IN 16 1,623.57",
    "# International Spends",
    "EMI / PERSONAL LOAN ON CREDIT CARDS",
    "Creation Date Finish Date No. of Installments EMI/Loan Amount Pending Installments Outstanding",
    "20/07/2026 20/12/2026 6 34,934.00 3 18,290.59 6,096.87",
]


def test_card_title_further_down_is_still_a_card_statement(client):
    card = _card(client, statement_day=15, due_value=20)
    att = add_email(ICICI_CARD_LINES, mid="icici-card", sender="ICICI <credit_cards@icicibank.com>")
    d = client.post("/api/statements", json={"attachment_id": att, "password": "test-pdf-pass"}).json()
    assert (d["doc_type"], d["account_id"]) == ("card_statement", card["id"])
    got = sorted((r["date"], r["amount"]) for r in d["rows"])
    assert got == [
        ("2026-09-18", -699_000),
        ("2026-10-01", -107_400),  # not glued to the credit limit box
        ("2026-10-03", 2_307_343),
        ("2026-10-17", -162_357),  # an expense, not "credit" from the EMI heading
    ]  # and no 20 Jul row from the EMI table
    f = d["figures"]
    assert (f["statement_date"], f["period_start"]) == ("2026-10-18", "2026-09-19")
    # the card is set to the 15th: the statement suggests the 18th
    assert (f["card_statement_day"], f["suggest_statement_day"]) == (15, 18)


def test_choosing_a_card_rereads_a_draft_the_card_way(client):
    bank = _bank(client)
    card = _card(client, last4="9999")
    lines = [ln for ln in ICICI_CARD_LINES if ln != "CREDIT CARD STATEMENT" and "Card Number" not in ln]
    lines = [ln for ln in lines if not ln.startswith(("Total Amount", "Minimum Amount", "Credit Limit"))]
    att = add_email(lines, mid="nocardword", sender="Someone <x@example.com>")
    d = client.post("/api/statements", json={"attachment_id": att, "password": "test-pdf-pass"}).json()
    assert d["doc_type"] == "bank_statement"
    d = client.patch(f"/api/statements/{d['id']}", json={"account_id": card["id"]}).json()
    assert d["doc_type"] == "card_statement" and d["account_id"] == card["id"]
    assert "2026-07-20" not in {r["date"] for r in d["rows"]}
    assert bank  # bank exists so the draft could have gone either way


def test_month_first_dates():
    s = parse_card_summary("Credit Card Statement\nStatement period : September 19, 2026 to October 18, 2026")
    assert (s.period_start, s.statement_date) == (date(2026, 9, 19), date(2026, 10, 18))

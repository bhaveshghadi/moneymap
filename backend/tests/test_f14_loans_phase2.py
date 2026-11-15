"""Loans phase 2: editing terms (and the spending mode), part-payments with the what-if,
floating-rate changes, and EMI / part-payment rows matched in bank statement import."""

from datetime import date

from app.core.dates import add_months
from app.modules.loans.maths import calc_emi

from .helpers import cat_id
from .test_statement_import import add_email

LAKH = 100_000 * 100
TODAY = date.today()
FIRST = add_months(TODAY.replace(day=5), 1)  # first EMI next month


def _loan(client, **extra):
    body = {"name": "Home loan", "lender": "HDFC", "kind": "home", "principal": 10 * LAKH, "rate": 10.5,
            "tenure": 60, "first_emi_date": FIRST.isoformat(), **extra}
    r = client.post("/api/loans", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _spending(client):
    return client.get("/api/transactions", params={"type": "withdrawal"}).json()["sum_out"]


def test_edit_terms(client, bank):
    loan = _loan(client, pay_from_id=bank["id"])
    r = client.patch(f"/api/loans/{loan['id']}", json={"principal": 8 * LAKH, "rate": 9.5, "tenure": 48})
    assert r.status_code == 200, r.text
    e = r.json()
    assert (e["principal"], e["rate"], e["tenure"], e["emi"]) == (8 * LAKH, 9.5, 48, calc_emi(8 * LAKH, 950, 48))
    assert len(e["schedule"]) == 48
    # the lender's own EMI figure is kept when given
    e = client.patch(f"/api/loans/{loan['id']}", json={"emi": 20_200_00}).json()
    assert e["emi"] == 20_200_00
    bad = client.patch(f"/api/loans/{loan['id']}", json={"emi": 1_000_00})
    assert bad.status_code == 422  # doesn't cover the interest


def test_change_spending_mode_re_records_emis(client, bank):
    loan = _loan(client, pay_from_id=bank["id"])
    client.post(f"/api/loans/{loan['id']}/pay", json={})
    first = loan["schedule"][0]
    assert _spending(client) == first["emi"]
    e = client.patch(f"/api/loans/{loan['id']}", json={"count_mode": "interest_only"}).json()
    assert e["count_mode"] == "interest_only" and e["paid_count"] == 1
    assert _spending(client) == first["interest"]  # the principal part is now a transfer to the loan
    client.patch(f"/api/loans/{loan['id']}", json={"count_mode": "whole_emi"})
    page = client.get("/api/transactions", params={"type": "withdrawal"}).json()
    assert page["sum_out"] == first["emi"] and page["total"] == 1  # merged back into one EMI expense


def test_what_if_and_part_payment(client, bank):
    loan = _loan(client, pay_from_id=bank["id"])
    w = client.post(f"/api/loans/{loan['id']}/what-if", json={"amount": 2 * LAKH, "mode": "reduce_tenure"}).json()
    assert w["outstanding"] == 10 * LAKH and w["after"]["emi"] == 21_494_00
    assert w["months_saved"] > 10 and w["interest_saved"] > 0
    e = client.post(f"/api/loans/{loan['id']}/what-if", json={"amount": 2 * LAKH, "mode": "reduce_emi"}).json()
    assert e["after"]["months"] == 60 and e["after"]["emi"] == calc_emi(8 * LAKH, 1050, 60)
    assert 0 < e["interest_saved"] < w["interest_saved"]  # a shorter loan saves more

    after = client.post(f"/api/loans/{loan['id']}/prepay", json={"date": TODAY.isoformat(), "amount": 2 * LAKH,
                                                                 "mode": "reduce_tenure", "fee": 500_00}).json()
    assert after["outstanding"] == 8 * LAKH and after["prepaid"] == 2 * LAKH
    assert len(after["schedule"]) == 60 - w["months_saved"] and after["current_emi"] == 21_494_00
    ev = after["events"][0]
    assert (ev["kind"], ev["amount"], ev["before_n"]) == ("prepay", 2 * LAKH, 1)
    # whole EMI loan: the part-payment counts as spending; the charge too
    assert _spending(client) == 2 * LAKH + 500_00
    # switch it to keep the end date instead: the EMI drops
    e2 = client.patch(f"/api/loans/{loan['id']}/events/{ev['id']}", json={"mode": "reduce_emi"}).json()
    assert len(e2["schedule"]) == 60 and e2["current_emi"] == calc_emi(8 * LAKH, 1050, 60)
    # undo it: the payment and the charge it made are removed
    e3 = client.delete(f"/api/loans/{loan['id']}/events/{ev['id']}").json()
    assert e3["outstanding"] == 10 * LAKH and e3["events"] == [] and _spending(client) == 0


def test_paying_it_all_closes_the_loan(client, bank):
    loan = _loan(client, pay_from_id=bank["id"], count_mode="interest_only")
    done = client.post(f"/api/loans/{loan['id']}/prepay", json={"date": TODAY.isoformat(), "amount": 10 * LAKH}).json()
    assert (done["status"], done["outstanding"], done["closed_on"]) == ("closed", 0, TODAY.isoformat())
    assert _spending(client) == 0  # interest-only loan: paying principal is a transfer


def test_rate_change(client, bank):
    loan = _loan(client, pay_from_id=bank["id"])
    on = add_months(FIRST, 5).replace(day=20).isoformat()
    up = client.post(f"/api/loans/{loan['id']}/rate", json={"date": on, "rate": 11.5, "mode": "reduce_tenure"}).json()
    assert up["current_emi"] == 21_494_00 and len(up["schedule"]) > 60  # same EMI, ends later
    assert up["schedule"][5]["interest"] == up["schedule"][4]["interest"] or up["schedule"][6]["interest"] > 0
    ev = up["events"][0]
    keep_end = client.patch(f"/api/loans/{loan['id']}/events/{ev['id']}", json={"mode": "reduce_emi"}).json()
    assert len(keep_end["schedule"]) == 60 and keep_end["schedule"][-1]["emi"] > 0
    assert keep_end["schedule"][7]["emi"] > 21_494_00  # a higher EMI from the change on
    w = client.post(f"/api/loans/{loan['id']}/what-if", json={"kind": "rate", "rate": 9.0, "mode": "reduce_emi"}).json()
    assert w["after"]["emi"] < w["before"]["emi"] and w["interest_saved"] > 0


def test_flat_rate_loans_cant_take_part_payments(client, bank):
    loan = _loan(client, method="flat", rate=10)
    r = client.post(f"/api/loans/{loan['id']}/prepay", json={"date": TODAY.isoformat(), "amount": LAKH})
    assert r.status_code == 422 and "reducing" in r.json()["detail"]


ICICI_LOAN_LINES = [
    "ICICI BANK STATEMENT",
    "Savings A/c XXXXXXXX2840",
    "DATE MODE PARTICULARS DEPOSITS WITHDRAWALS BALANCE",
    "01-11-2026 B/F 5,00,000.00",
    "05-11-2026 BIL/INFT/FJ50648566/Personal Loan XX70363 EMI 13,462.00 4,86,538.00",
    "19-11-2026 SMP/Payment Against Loan A/C No.LPMUM00048870363 1,63,234.00 3,23,304.00",
    "20-11-2026 UPI/SWIGGY/swiggy@ybl/food/ICICI 450.00 3,22,854.00",
]


def test_bank_statement_matches_emi_and_part_payment(client):
    acct = client.post("/api/accounts", json={"name": "ICICI Savings", "type": "asset", "account_number": "XXXX2840",
                                              "opening_balance": 50_000_000}).json()
    loan = _loan(client, name="Personal loan", kind="personal", lender="ICICI Bank", loan_number="LPMUM00048870363",
                 method="emi_only", principal=4 * LAKH, emi=13_462_00, tenure=36, rate=None,
                 first_emi_date="2026-03-05", start="existing", paid_before=8, pay_from_id=acct["id"])
    assert loan["paid_count"] == 8
    att = add_email(ICICI_LOAN_LINES, mid="loan-stmt")
    d = client.post("/api/statements", json={"attachment_id": att, "password": "test-pdf-pass"}).json()
    emi = next(r for r in d["rows"] if "Personal Loan" in r["description"])
    pre = next(r for r in d["rows"] if "Against Loan" in r["description"])
    assert (emi["loan_id"], emi["loan_action"], emi["category_id"]) == (loan["loan_id"], "emi", cat_id(client, "Loan / EMI"))
    assert (pre["loan_id"], pre["loan_action"], pre["status"]) == (loan["loan_id"], "prepay", "ready")
    assert pre["suggestion"].startswith("Part-payment on Personal loan")
    swiggy = next(r for r in d["rows"] if "SWIGGY" in r["description"])
    assert swiggy["loan_id"] is None
    client.patch(f"/api/statements/{d['id']}/rows/{swiggy['id']}", json={"leave_uncategorised": True})
    assert client.post(f"/api/statements/{d['id']}/import").json()["imported"] == 3
    after = client.get(f"/api/loans/{loan['id']}").json()
    assert after["paid_count"] == 9 and after["prepaid"] == 1_63_234_00
    assert after["events"][0]["kind"] == "prepay" and after["events"][0]["mode"] == "reduce_tenure"


def test_unlinking_a_statement_row_from_the_loan(client):
    acct = client.post("/api/accounts", json={"name": "ICICI Savings", "type": "asset", "account_number": "XXXX2840",
                                              "opening_balance": 50_000_000}).json()
    loan = _loan(client, name="Personal loan", lender="ICICI Bank", loan_number="70363", method="emi_only",
                 principal=4 * LAKH, emi=13_462_00, tenure=36, rate=None, first_emi_date="2026-03-05",
                 start="existing", paid_before=8, pay_from_id=acct["id"])
    att = add_email(ICICI_LOAN_LINES, mid="loan-stmt2")
    d = client.post("/api/statements", json={"attachment_id": att, "password": "test-pdf-pass"}).json()
    pre = next(r for r in d["rows"] if "Against Loan" in r["description"])
    r = client.patch(f"/api/statements/{d['id']}/rows/{pre['id']}", json={"loan_id": None}).json()
    assert r["loan_id"] is None and r["loan_action"] is None
    assert loan["paid_count"] == 8

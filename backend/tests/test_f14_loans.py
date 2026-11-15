"""Loans (F14 phase 1): EMI maths (vectors from the earlier build), adding new and
running loans, recording EMIs both ways (whole EMI / interest only), moving past
EMI expenses onto a loan, net worth, Overview dues and the emergency fund."""

from datetime import date, timedelta

from app.core.dates import add_months
from app.modules.loans.maths import build, build_flat, calc_emi, flat_emi, implied_rate_bp, what_if

from .helpers import cat_id, spend

LAKH = 100_000 * 100  # ₹1,00,000 in paise
TODAY = date.today()


# ---------------------------------------------------------------- maths


def test_emi_formula_and_schedule():
    # ₹10 lakh at 10.5% for 5 years -> ₹21,494 a month (standard EMI tables)
    assert calc_emi(10 * LAKH, 1050, 60) == 21_494_00
    assert calc_emi(12_000_00, 0, 12) == 1_000_00
    rows = build(10 * LAKH, 1050, 21_494_00, 60, date(2026, 1, 31))
    assert len(rows) == 60 and rows[-1].balance == 0
    assert sum(r.principal for r in rows) == 10 * LAKH
    assert rows[0].interest == 8_750_00  # 10 lakh x 10.5% / 12
    assert rows[0].principal + rows[0].interest == 21_494_00
    assert rows[1].date == date(2026, 2, 28) and rows[2].date == date(2026, 3, 31)  # month-end kept
    assert abs(rows[-1].emi - 21_494_00) < 100_00  # last EMI only slightly adjusted


def test_flat_rate_and_emi_only():
    # ₹1 lakh at 10% flat for 1 year: ₹10,000 interest, ₹1,10,000 payable, ₹9,167 a month
    assert flat_emi(LAKH, 1000, 12) == 9_167_00
    rows = build_flat(LAKH, 1000, 12, date(2026, 1, 5))
    assert sum(r.principal for r in rows) == LAKH and sum(r.interest for r in rows) == 10_000_00
    assert rows[-1].balance == 0
    # the rate is worked out back from amount + EMI + months
    assert implied_rate_bp(10 * LAKH, 21_494_00, 60) == 1050


def test_prepayment_what_if():
    rows = build(10 * LAKH, 1050, 21_494_00, 60, date(2026, 1, 31))
    t = what_if(rows, 0, 1050, 21_494_00, 2 * LAKH, "reduce_tenure")
    assert t["outstanding"] == 10 * LAKH and t["after"]["emi"] == 21_494_00
    assert t["months_saved"] > 10 and t["interest_saved"] > 0
    e = what_if(rows, 0, 1050, 21_494_00, 2 * LAKH, "reduce_emi")
    assert e["after"]["months"] == 60 and e["after"]["emi"] == calc_emi(8 * LAKH, 1050, 60)
    assert 0 < e["interest_saved"] < t["interest_saved"]


# ---------------------------------------------------------------- API


def _loan(client, **extra):
    body = {"name": "Home loan", "lender": "HDFC", "kind": "home", "principal": 10 * LAKH, "rate": 10.5,
            "tenure": 60, "first_emi_date": add_months(TODAY.replace(day=5), 1).isoformat(), **extra}
    r = client.post("/api/loans", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _spending(client):
    return client.get("/api/transactions", params={"type": "withdrawal"}).json()["sum_out"]


def test_needs_login(anon):
    assert anon.get("/api/loans").status_code == 401


def test_new_loan_whole_emi(client, bank):
    loan = _loan(client, pay_from_id=bank["id"])
    assert (loan["emi"], loan["outstanding"], loan["paid_count"], loan["count_mode"], loan["status"]) == (
        21_494_00, 10 * LAKH, 0, "whole_emi", "active"
    )
    assert len(loan["schedule"]) == 60 and loan["next"]["n"] == 1
    # paid straight to the seller and counted as whole EMIs: nothing is spent up front
    assert _spending(client) == 0
    o = client.get("/api/overview").json()
    assert o["loans_owed"] == 10 * LAKH and o["net_worth"] == bank["balance"] - 10 * LAKH
    assert [d["loan_id"] for d in o["loan_dues"]] == [loan["id"]]

    paid = client.post(f"/api/loans/{loan['id']}/pay", json={}).json()
    assert paid["paid_count"] == 1 and paid["schedule"][0]["paid"] is True
    assert paid["outstanding"] == 10 * LAKH - loan["schedule"][0]["principal"]
    page = client.get("/api/transactions", params={"type": "withdrawal"}).json()
    assert page["sum_out"] == 21_494_00 and page["items"][0]["category"]["name"] == "Loan / EMI"  # whole EMI = spending


def test_new_loan_interest_only_with_money_received(client, bank):
    loan = _loan(client, name="Personal loan", kind="personal", count_mode="interest_only", money="received",
                 received_into_id=bank["id"], pay_from_id=bank["id"], disbursed_date=TODAY.isoformat())
    balances = {a["name"]: a["balance"] for a in client.get("/api/accounts").json()}
    assert balances["Bank"] == bank["balance"] + 10 * LAKH  # the loan money came in — not income
    assert client.get("/api/transactions", params={"type": "deposit"}).json()["total"] == 0
    paid = client.post(f"/api/loans/{loan['id']}/pay", json={}).json()
    first = loan["schedule"][0]
    assert _spending(client) == first["interest"]  # only the interest counts as spending
    assert paid["interest_paid"] == first["interest"] and paid["outstanding"] == 10 * LAKH - first["principal"]
    balances = {a["name"]: a["balance"] for a in client.get("/api/accounts").json()}
    assert balances["Bank"] == bank["balance"] + 10 * LAKH - 21_494_00  # the whole EMI left the bank
    o = client.get("/api/overview").json()
    assert o["net_worth"] == balances["Bank"] - paid["outstanding"]


def test_running_loan_links_past_emis(client, bank):
    emi_cat = cat_id(client, "Loan / EMI")
    first = add_months(TODAY.replace(day=5), -6)
    # three past EMIs saved as expenses (e.g. from bank statements), one unrelated expense
    for k in (3, 4, 5):
        spend(client, bank, 13_462_00, desc="BIL/INFT/Personal Loan XX70363 EMI", payee="Bank",
              date=add_months(first, k).isoformat(), category_id=emi_cat)
    spend(client, bank, 500_00, desc="Lunch", date=TODAY.isoformat())
    cands = client.get("/api/loans/candidates", params={"emi": 13_462_00, "loan_number": "70363"}).json()
    assert len(cands) == 3 and all(c["suggested"] and c["emi_like"] for c in cands)
    loan = _loan(client, name="Personal loan", kind="personal", method="emi_only", principal=4 * LAKH,
                 emi=13_462_00, tenure=36, rate=None, start="existing", loan_number="XX70363",
                 first_emi_date=first.isoformat(), link_ids=[c["transaction_id"] for c in cands])
    due_so_far = sum(1 for r in loan["schedule"] if date.fromisoformat(r["date"]) < TODAY)
    assert loan["paid_count"] == due_so_far  # the linked ones are among those, not counted twice
    assert loan["rate_worked_out"] is True and 10 < loan["rate"] < 20
    page = client.get("/api/transactions", params={"loan_id": loan["loan_id"]}).json()
    assert page["total"] == 3
    # a part-payment amount isn't an EMI (part-payments come in phase 2)
    big = spend(client, bank, 1_63_234_00, desc="Payment Against Loan A/C 70363", date=TODAY.isoformat())
    r = client.post(f"/api/loans/{loan['id']}/link", json={"transaction_ids": [big["id"]]})
    assert r.status_code == 422 and "part-payment" in r.json()["detail"]


def test_emergency_fund_includes_loan_emis(client, bank):
    rent = cat_id(client, "Rent")
    for n in (3, 2, 1):
        spend(client, bank, 20_000_00, category_id=rent, date=add_months(TODAY.replace(day=1), -n, 10).isoformat())
    loan = _loan(client, pay_from_id=bank["id"], first_emi_date=add_months(TODAY.replace(day=5), -2).isoformat(),
                 start="existing")
    e = client.put("/api/emergency-fund", json={"account_id": bank["id"], "average_months": 3}).json()
    assert e["loan_emis"] == 21_494_00
    assert e["monthly_essential"] == 20_000_00 + 21_494_00
    # recording an EMI doesn't count it twice (EMI expenses are left out of the history)
    client.post(f"/api/loans/{loan['id']}/pay", json={})
    assert client.get("/api/emergency-fund").json()["monthly_essential"] == 20_000_00 + 21_494_00


def test_validation_and_delete(client, bank):
    assert client.post("/api/loans", json={"name": "X", "tenure": 12, "first_emi_date": "2026-12-05"}).status_code == 422
    r = client.post("/api/loans", json={"name": "X", "method": "emi_only", "emi": 5_000_00, "tenure": 12,
                                        "first_emi_date": "2026-12-05", "count_mode": "interest_only"})
    assert r.status_code == 422  # can't split without the amount
    r = client.post("/api/loans", json={"name": "X", "principal": 10 * LAKH, "rate": 12, "emi": 5_000_00,
                                        "tenure": 60, "first_emi_date": "2026-12-05"})
    assert r.status_code == 422 and "interest" in r.json()["detail"]  # EMI below the monthly interest
    assert client.post("/api/accounts", json={"name": "L", "type": "loan"}).status_code == 422

    loan = _loan(client, count_mode="interest_only", money="received", received_into_id=bank["id"],
                 pay_from_id=bank["id"])
    client.post(f"/api/loans/{loan['id']}/pay", json={})
    assert client.delete(f"/api/loans/{loan['id']}").status_code == 204
    assert client.get(f"/api/loans/{loan['id']}").status_code == 404
    # the money-received entry went with it; the EMI stays as an expense, full amount, in Loan / EMI
    assert client.get("/api/transactions", params={"type": "transfer"}).json()["total"] == 0
    page = client.get("/api/transactions", params={"type": "withdrawal"}).json()
    assert {t["category"]["name"] for t in page["items"]} == {"Loan / EMI", "Loan Interest"}


def test_emi_only_without_amount_is_whole_emi(client, bank):
    loan = _loan(client, method="emi_only", principal=None, rate=None, emi=2_000_00, tenure=10,
                 first_emi_date=(TODAY + timedelta(days=10)).isoformat())
    assert (loan["outstanding"], loan["total_interest"], loan["total_payable"]) == (20_000_00, 0, 20_000_00)

"""F18 Savings plan: needs / wants / savings against a rule, the income basis, suggestions,
and budgets made from the rule (budgets that count their categories by themselves).
All amounts here are made up."""

from datetime import date

from app.core.dates import add_months

from .helpers import cat_id
from .test_f14_loans import _loan

RS = 100  # paise
K = 1_000 * RS  # ₹1,000


def _txn(client, bank, kind, amount, desc, on, category=None, **extra):
    body = {"type": kind, "date": on, "amount": amount, "description": desc, **extra}
    if kind == "withdrawal":
        body |= {"source_id": bank["id"]}
    elif kind == "deposit":
        body |= {"destination_id": bank["id"]}
    if category:
        body["category_id"] = cat_id(client, category)
    r = client.post("/api/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _month(client, bank, m: date):
    """A made-up month: ₹1,00,000 salary; needs ₹40,000; wants ₹30,000 (₹5,000 uncategorised);
    ₹5,000 "Investment" spending + ₹10,000 moved to a fund; ₹2,000 set aside in a piggy bank."""
    on = m.replace(day=5).isoformat()
    _txn(client, bank, "deposit", 100 * K, "Salary", on, "Salary")
    _txn(client, bank, "withdrawal", 30 * K, "Rent", on, "Rent")
    _txn(client, bank, "withdrawal", 10 * K, "Groceries", on, "Groceries")
    _txn(client, bank, "withdrawal", 15 * K, "Dinners", on, "Dining")
    _txn(client, bank, "withdrawal", 10 * K, "Clothes", on, "Shopping")
    _txn(client, bank, "withdrawal", 5 * K, "UPI something", on)
    _txn(client, bank, "withdrawal", 5 * K, "SIP", on, "Investment")
    fund = client.get("/api/investments").json()
    if not fund:
        fund = [client.post("/api/investments", json={"kind": "mf", "quantity": 1,
                                                       "fund": {"scheme": "Example Fund"}}).json()]  # fmt: skip
    _txn(client, bank, "transfer", 10 * K, "To the fund", on, source_id=bank["id"], destination_id=fund[0]["id"])
    piggy = client.get("/api/piggy-banks").json()
    if not piggy:
        piggy = [client.post("/api/piggy-banks", json={"name": "Trip", "account_id": bank["id"],
                                                        "target_amount": 50 * K}).json()]  # fmt: skip
    r = client.post(f"/api/piggy-banks/{piggy[0]['id']}/events", json={"amount": 2 * K, "date": on})
    assert r.status_code == 201, r.text


M = "2026-10"


def test_split_with_50_30_20(client, bank):
    _month(client, bank, date(2026, 10, 1))
    p = client.get("/api/savings-plan", params={"month": M}).json()
    assert p["settings"]["rule"] == "50_30_20" and p["income"] == p["income_used"] == 100 * K
    assert (p["needs"]["amount"], p["needs"]["pct"], p["needs"]["target"]) == (40 * K, 40.0, 50 * K)
    assert (p["wants"]["amount"], p["wants"]["diff"]) == (30 * K, 0)
    assert (p["savings"]["amount"], p["savings"]["target"], p["savings"]["diff"]) == (30 * K, 20 * K, 10 * K)
    assert p["savings_split"] == {"to_investments": 15 * K, "to_goals": 2 * K, "left_in_bank": 13 * K}
    assert p["uncategorised"] == 5 * K
    assert [x["name"] for x in p["needs_lines"]] == ["Rent", "Groceries"]
    kinds = [s["kind"] for s in p["suggestions"]]
    assert kinds[0] == "on_track" and "invest_extra" in kinds and "uncategorised" in kinds


def test_custom_rule_wants_over(client, bank):
    _month(client, bank, date(2026, 10, 1))
    bad = client.put("/api/savings-plan/settings", json={"rule": "custom", "needs": 60, "wants": 30, "savings": 20})
    assert bad.status_code == 422
    r = client.put("/api/savings-plan/settings", json={"rule": "custom", "needs": 60, "wants": 20, "savings": 20})
    assert r.status_code == 200 and r.json()["wants"] == 20
    p = client.get("/api/savings-plan", params={"month": M}).json()
    (w,) = [s for s in p["suggestions"] if s["kind"] == "wants_over"]
    assert w["amount"] == 10 * K
    cuts = {x["name"]: x["amount"] for x in w["items"]}
    assert set(cuts) == {"Dining", "Shopping", "Uncategorised"} and cuts["Dining"] == 5 * K  # 15/30 of ₹10,000


def test_pay_yourself_first_and_fixed_income(client, bank):
    _month(client, bank, date(2026, 10, 1))
    assert client.put("/api/savings-plan/settings", json={"rule": "80_20", "basis": "fixed"}).status_code == 422
    client.put("/api/savings-plan/settings", json={"rule": "80_20", "basis": "fixed", "fixed_income": 120 * K})
    p = client.get("/api/savings-plan", params={"month": M}).json()
    assert p["needs"]["target"] is None and p["wants"]["target"] is None  # not judged one by one
    assert p["income_used"] == 120 * K and p["spending"]["target"] == 96 * K and p["spending"]["amount"] == 70 * K
    assert p["savings"]["amount"] == 50 * K  # 1,20,000 − 70,000


def test_loan_emi_is_a_need_and_emi_warning(client, bank):
    loan = _loan(client, pay_from_id=bank["id"], principal=200 * 100 * K, rate=10.0, tenure=60)
    client.post(f"/api/loans/{loan['id']}/pay", json={"date": "2026-10-05"})
    _txn(client, bank, "deposit", 100 * K, "Salary", "2026-10-01", "Salary")
    p = client.get("/api/savings-plan", params={"month": M}).json()
    emi = loan["emi"]
    assert p["needs_lines"][0]["name"] == "Loan EMIs" and p["needs"]["amount"] == emi
    assert p["emi_monthly"] == emi and emi * 100 > 40 * 100 * K
    assert "emi_high" in [s["kind"] for s in p["suggestions"]]


def test_no_income(client, bank):
    p = client.get("/api/savings-plan", params={"month": M}).json()
    assert [s["kind"] for s in p["suggestions"]] == ["no_income"]


def test_budgets_from_the_rule(client, bank):
    last = add_months(date.today().replace(day=1), -1, 1)
    _month(client, bank, last)
    pr = client.get("/api/savings-plan/budgets").json()
    # the 3-month average: ₹1,00,000 / 3 income, so the wants share is 30% of that
    assert pr["wants_target"] == round(100 * K / 3 * 0.3)
    names = [x["name"] for x in pr["items"]]
    assert names == ["Dining", "Shopping"] and pr["taken"] == []  # uncategorised can't have a budget
    picks = [{"category_id": x["category_id"], "amount": x["amount"]} for x in pr["items"]]
    r = client.post("/api/savings-plan/budgets", json={"items": picks})
    assert r.status_code == 201, r.text
    # the budget counts its category by itself — no budget set on the expense
    dining = next(b for b in client.get("/api/budgets", params={"month": f"{last:%Y-%m}"}).json()["budgets"]
                  if b["name"] == "Dining")  # fmt: skip
    assert dining["spent"] == 15 * K and dining["mode"] == "fixed"
    assert dining["category_ids"] == [cat_id(client, "Dining")]
    again = client.get("/api/savings-plan/budgets").json()
    assert again["items"] == [] and {x["budget_name"] for x in again["taken"]} == {"Dining", "Shopping"}
    # a category counts in one budget only
    r = client.post("/api/budgets", json={"name": "Eating out", "category_ids": [cat_id(client, "Dining")]})
    assert r.status_code == 422


def test_budget_categories_and_unbudgeted(client, bank):
    on = "2026-10-05"
    _txn(client, bank, "withdrawal", 3 * K, "Dinner", on, "Dining")
    other = client.post("/api/budgets", json={"name": "Treats"}).json()
    _txn(client, bank, "withdrawal", 2 * K, "Cake", on, "Dining", budget_id=other["id"])  # put in another by hand
    b = client.post("/api/budgets", json={"name": "Food out", "mode": "fixed", "amount": 10 * K,
                                          "category_ids": [cat_id(client, "Dining")]}).json()  # fmt: skip
    month = client.get("/api/budgets", params={"month": M}).json()
    spent = {x["name"]: x["spent"] for x in month["budgets"]}
    assert spent == {"Food out": 3 * K, "Treats": 2 * K} and month["unbudgeted_spent"] == 0
    client.patch(f"/api/budgets/{b['id']}", json={"category_ids": []})
    month = client.get("/api/budgets", params={"month": M}).json()
    assert month["unbudgeted_spent"] == 3 * K


def test_transactions_filter_by_budget_includes_its_categories(client, bank):
    on = "2026-10-05"
    _txn(client, bank, "withdrawal", 3 * K, "Dinner", on, "Dining")
    _txn(client, bank, "withdrawal", 1 * K, "Tea", on, "Shopping")
    b = client.post("/api/budgets", json={"name": "Food out", "category_ids": [cat_id(client, "Dining")]}).json()
    page = client.get("/api/transactions", params={"budget_id": b["id"]}).json()
    assert [t["description"] for t in page["items"]] == ["Dinner"]
    page = client.get("/api/transactions", params={"no_budget": 1}).json()
    assert [t["description"] for t in page["items"]] == ["Tea"]

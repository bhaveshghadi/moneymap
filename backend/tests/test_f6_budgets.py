"""F6: budgets (manual / fixed / rollover) and the budget on expenses."""

from datetime import date, datetime

from app.core.dates import add_months

from .helpers import spend

TODAY = date.today()
THIS_MONTH = TODAY.strftime("%Y-%m")


def test_budgets_need_login(anon):
    assert anon.get("/api/budgets").status_code == 401


def test_manual_amount_and_spent(client, bank):
    b = client.post("/api/budgets", json={"name": "Food"}).json()
    assert (b["mode"], b["limit"], b["left"]) == ("manual", None, None)
    r = client.put(f"/api/budgets/{b['id']}/limits/{THIS_MONTH}", json={"amount": 500_000})
    assert r.json()["limit"] == 500_000 and r.json()["limit_is_auto"] is False
    spend(client, bank, 120_000, budget_id=b["id"], date=TODAY.isoformat())
    spend(client, bank, 30_000, date=TODAY.isoformat())  # no budget
    month = client.get(f"/api/budgets?month={THIS_MONTH}").json()
    food = month["budgets"][0]
    assert (food["spent"], food["left"]) == (120_000, 380_000)
    assert (month["budgeted"], month["spent"], month["unbudgeted_spent"]) == (500_000, 120_000, 30_000)
    # clearing the month's amount
    assert client.delete(f"/api/budgets/{b['id']}/limits/{THIS_MONTH}").json()["limit"] is None


def test_fixed_amount_and_hand_set_month(client):
    b = client.post("/api/budgets", json={"name": "Fun", "mode": "fixed", "amount": 200_000}).json()
    assert (b["limit"], b["limit_is_auto"]) == (200_000, True)
    # changing the amount works the current month out again
    b = client.patch(f"/api/budgets/{b['id']}", json={"amount": 250_000}).json()
    assert b["limit"] == 250_000
    # an amount set by hand wins and survives later changes
    client.put(f"/api/budgets/{b['id']}/limits/{THIS_MONTH}", json={"amount": 99_000})
    b = client.patch(f"/api/budgets/{b['id']}", json={"amount": 300_000}).json()
    assert (b["limit"], b["limit_is_auto"]) == (99_000, False)
    # future months are not filled in
    nxt = add_months(TODAY.replace(day=1), 1).strftime("%Y-%m")
    assert client.get(f"/api/budgets?month={nxt}").json()["budgets"][0]["limit"] is None
    # switching to manual leaves months without a hand-set amount empty
    client.delete(f"/api/budgets/{b['id']}/limits/{THIS_MONTH}")
    assert client.patch(f"/api/budgets/{b['id']}", json={"mode": "manual"}).json()["limit"] is None


def _created_last_month(budget_id: int) -> date:
    from app.db import SessionLocal
    from app.models import Budget, BudgetLimit

    prev = add_months(TODAY.replace(day=1), -1)
    with SessionLocal() as db:
        db.get(Budget, budget_id).created_at = datetime(prev.year, prev.month, 1)
        db.query(BudgetLimit).delete()
        db.commit()
    return prev


def test_rollover_carries_leftover(client, bank):
    b = client.post("/api/budgets", json={"name": "Groceries", "mode": "rollover", "amount": 100_000}).json()
    prev = _created_last_month(b["id"])
    spend(client, bank, 30_000, budget_id=b["id"], date=prev.replace(day=15).isoformat())
    assert client.get(f"/api/budgets?month={prev:%Y-%m}").json()["budgets"][0]["limit"] == 100_000
    assert client.get(f"/api/budgets?month={THIS_MONTH}").json()["budgets"][0]["limit"] == 100_000 + 70_000


def test_rollover_never_below_zero(client, bank):
    b = client.post("/api/budgets", json={"name": "Shopping", "mode": "rollover", "amount": 100_000}).json()
    prev = _created_last_month(b["id"])
    spend(client, bank, 250_000, budget_id=b["id"], date=prev.replace(day=10).isoformat())  # overspent by ₹1,500
    assert client.get(f"/api/budgets?month={THIS_MONTH}").json()["budgets"][0]["limit"] == 0


def test_budget_validation(client):
    client.post("/api/budgets", json={"name": "Food"})
    assert client.post("/api/budgets", json={"name": "Food"}).status_code == 409
    assert client.post("/api/budgets", json={"name": "  "}).status_code == 422
    assert client.post("/api/budgets", json={"name": "X", "mode": "weekly"}).status_code == 422
    assert client.post("/api/budgets", json={"name": "Y", "amount": -1}).status_code == 422
    assert client.get("/api/budgets?month=2026-13").status_code == 422
    assert client.patch("/api/budgets/9999", json={"name": "Z"}).status_code == 404


def test_budget_only_on_expenses_and_filters(client, bank):
    b = client.post("/api/budgets", json={"name": "Food"}).json()
    t = spend(client, bank, 500, budget_id=b["id"])
    assert t["budget"] == {"id": b["id"], "name": "Food"}
    spend(client, bank, 700)
    dep = client.post("/api/transactions", json={"type": "deposit", "date": "2026-11-05", "amount": 500, "description": "x",
                                                 "source_name": "Employer", "destination_id": bank["id"], "budget_id": b["id"]})
    assert dep.json()["budget"] is None  # income never carries a budget
    assert client.get(f"/api/transactions?budget_id={b['id']}").json()["total"] == 1
    assert client.get("/api/transactions?no_budget=true").json()["total"] == 1  # expenses only
    bad = client.post("/api/transactions", json={"type": "withdrawal", "date": "2026-11-05", "amount": 5, "description": "x",
                                                 "source_id": bank["id"], "destination_name": "S", "budget_id": 9999})
    assert bad.status_code == 422


def test_deleting_budget_keeps_transactions(client, bank):
    b = client.post("/api/budgets", json={"name": "Temp"}).json()
    t = spend(client, bank, 1_000, budget_id=b["id"])
    assert client.delete(f"/api/budgets/{b['id']}").status_code == 204
    assert client.get(f"/api/transactions/{t['id']}").json()["budget"] is None


def test_overview_shows_budgets_with_amount_or_spending(client, bank):
    food = client.post("/api/budgets", json={"name": "Food", "mode": "fixed", "amount": 100_000}).json()
    client.post("/api/budgets", json={"name": "Empty"})  # no amount, no spending -> hidden
    off = client.post("/api/budgets", json={"name": "Off", "mode": "fixed", "amount": 5_000, "active": False}).json()
    spend(client, bank, 40_000, budget_id=food["id"], date=TODAY.isoformat())
    o = client.get(f"/api/overview?month={THIS_MONTH}").json()
    assert [(b["name"], b["limit"], b["spent"]) for b in o["budgets"]] == [("Food", 100_000, 40_000)]
    assert all(b["id"] != off["id"] for b in o["budgets"])

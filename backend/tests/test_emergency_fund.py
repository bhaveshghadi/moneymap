"""Emergency fund: typical month of essential spending × months of cover, held in a special piggy bank."""

import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from app.core.dates import add_months
from app.modules.emergency.service import essential_history, median, status_for

from .helpers import cat_id, spend

TODAY = date.today()
THIS_MONTH = TODAY.replace(day=1)


def month_day(n_back: int, day: int = 10) -> str:
    """A date in the month `n_back` months before this one."""
    return add_months(THIS_MONTH, -n_back, day).isoformat()


def _setup(client, bank, **extra):
    r = client.put("/api/emergency-fund", json={"account_id": bank["id"], **extra})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- maths


def test_median():
    assert median([]) == 0
    assert median([5]) == 5
    # the ₹62,000 spike barely moves it: middle values ₹39,000 and ₹40,000 -> ₹39,500
    assert median([3_900_000, 4_100_000, 3_600_000, 4_000_000, 6_200_000, 3_900_000]) == 3_950_000
    assert median([10, 20, 30, 41]) == 25  # mean of the two middle values


def test_status():
    assert status_for(0, 0, 0) == "no_data"
    assert status_for(100, 50, 600) == "low"  # half a month
    assert status_for(100, 150, 600) == "building"
    assert status_for(100, 300, 600) == "safe"
    assert status_for(100, 600, 600) == "done"


# ---------------------------------------------------------------- API


def test_needs_login(anon):
    assert anon.get("/api/emergency-fund").status_code == 401


def test_starter_categories_marked_essential(client):
    cats = {c["name"]: c for c in client.get("/api/categories").json()}
    assert cats["Rent"]["essential"] and cats["Groceries"]["essential"] and cats["Loan / EMI"]["essential"]
    assert not cats["Dining"]["essential"] and not cats["Shopping"]["essential"]
    assert not cats["Salary"]["essential"]  # income is never essential
    assert sum(c["essential"] for c in cats.values()) == 20


def test_essential_switch_on_categories(client):
    c = client.post("/api/categories", json={"name": "Pet food", "essential": True}).json()
    assert c["essential"] is True
    assert client.patch(f"/api/categories/{c['id']}", json={"essential": False}).json()["essential"] is False
    inc = client.post("/api/categories", json={"name": "Side gig", "kind": "income", "essential": True}).json()
    assert inc["essential"] is False
    # turning a category into income drops the flag
    c2 = client.post("/api/categories", json={"name": "Odd", "essential": True}).json()
    assert client.patch(f"/api/categories/{c2['id']}", json={"kind": "income"}).json()["essential"] is False


def test_not_set_up(client):
    e = client.get("/api/emergency-fund").json()
    assert e["configured"] is False and e["status"] == "not_set_up" and len(e["essential_categories"]) == 20
    assert client.get("/api/overview").json()["emergency"] is None


def test_target_from_essential_spending(client, bank):
    rent, food, dining = cat_id(client, "Rent"), cat_id(client, "Groceries"), cat_id(client, "Dining")
    # six complete months: essential spending 39k, 41k, 36k, 40k, 62k (spike), 39k
    for n_back, amount in zip(range(6, 0, -1), [39, 41, 36, 40, 62, 39], strict=True):
        spend(client, bank, amount * 100_000 - 500_000, category_id=rent, date=month_day(n_back, 5))
        spend(client, bank, 500_000, category_id=food, date=month_day(n_back, 12))
        spend(client, bank, 900_000, category_id=dining, date=month_day(n_back, 20))  # not essential
    spend(client, bank, 9_900_000, category_id=rent, date=TODAY.isoformat())  # current month: left out
    client.post("/api/transactions", json={"type": "deposit", "date": month_day(2), "amount": 5_000_000,
                                           "description": "Salary", "source_name": "Employer", "destination_id": bank["id"]})
    e = _setup(client, bank)
    assert [h["amount"] for h in e["history"]] == [3_900_000, 4_100_000, 3_600_000, 4_000_000, 6_200_000, 3_900_000]
    assert (e["monthly_essential"], e["monthly_source"], e["months_of_data"]) == (3_950_000, "median", 6)
    assert e["target"] == 3_950_000 * 6
    assert e["piggy"]["name"] == "Emergency fund" and e["piggy"]["is_emergency"] is True
    assert e["piggy"]["target_amount"] == e["target"]  # the piggy bank's target follows
    # 3 months of cover, averaged over the last 3 months
    e = _setup(client, bank, months_cover=3, average_months=3)
    assert (e["monthly_essential"], e["target"]) == (4_000_000, 12_000_000)


def test_estimates_for_every_window_even_before_setup(client, bank):
    rent = cat_id(client, "Rent")
    # 12 complete months: ₹10,000 a month for the oldest 9, ₹40,000 a month for the latest 3
    for n_back in range(12, 0, -1):
        spend(client, bank, 4_000_000 if n_back <= 3 else 1_000_000, category_id=rent, date=month_day(n_back))
    e = client.get("/api/emergency-fund").json()
    assert e["configured"] is False
    by = {x["average_months"]: (x["monthly"], x["source"], x["months_of_data"]) for x in e["estimates"]}
    assert by == {3: (4_000_000, "median", 3), 6: (2_500_000, "median", 6), 12: (1_000_000, "median", 12)}
    # the same list comes with the set-up fund, so the settings can preview any choice
    assert len(_setup(client, bank)["estimates"]) == 3


def test_months_of_cover_up_to_five_years(client, bank):
    e = _setup(client, bank, monthly_override=1_000_000, months_cover=60)
    assert (e["months_cover"], e["target"]) == (60, 60_000_000)
    assert client.put("/api/emergency-fund", json={"account_id": bank["id"], "months_cover": 61}).status_code == 422
    assert client.put("/api/emergency-fund", json={"account_id": bank["id"], "months_cover": 0}).status_code == 422


def test_short_history_is_an_estimate(client, bank):
    spend(client, bank, 2_000_000, category_id=cat_id(client, "Rent"), date=month_day(1))
    e = _setup(client, bank)
    assert (e["months_of_data"], e["monthly_source"], e["monthly_essential"]) == (1, "estimate", 2_000_000)


def test_no_history_and_own_amount(client, bank):
    e = _setup(client, bank)
    assert (e["monthly_source"], e["status"], e["target"], e["covered_months"]) == ("none", "no_data", 0, None)
    e = _setup(client, bank, monthly_override=3_000_000)
    assert (e["monthly_source"], e["monthly_essential"], e["target"]) == ("override", 3_000_000, 18_000_000)


def test_saving_and_status(client, bank):
    e = _setup(client, bank, monthly_override=1_000_000, months_cover=6)  # target ₹60,000; bank has ₹1,00,000
    pid = e["piggy"]["id"]
    client.post(f"/api/piggy-banks/{pid}/events", json={"amount": 500_000})
    e = client.get("/api/emergency-fund").json()
    assert (e["saved"], e["covered_months"], e["status"]) == (500_000, 0.5, "low")
    client.post(f"/api/piggy-banks/{pid}/events", json={"amount": 2_500_000})
    e = client.get("/api/emergency-fund").json()
    assert (e["covered_months"], e["status"]) == (3.0, "safe")
    # the set-aside limit still applies (₹70,000 free, ₹1,00,000 asked)
    assert client.post(f"/api/piggy-banks/{pid}/events", json={"amount": 10_000_000}).status_code == 422
    client.post(f"/api/piggy-banks/{pid}/events", json={"amount": 3_000_000})
    assert client.get("/api/emergency-fund").json()["status"] == "done"
    o = client.get("/api/overview").json()["emergency"]
    assert o == {"target": 6_000_000, "saved": 6_000_000, "months_cover": 6, "covered_months": 6.0, "status": "done"}


def test_moving_and_switching_off(client, bank):
    cash = client.post("/api/accounts", json={"name": "Wallet", "type": "cash", "opening_balance": 500_000}).json()
    e = _setup(client, bank, monthly_override=100_000)
    pid = e["piggy"]["id"]
    payee = spend(client, bank, 100)["destination"]
    assert client.put("/api/emergency-fund", json={"account_id": payee["id"]}).status_code == 422  # not bank/cash
    client.post(f"/api/piggy-banks/{pid}/events", json={"amount": 1_000})
    r = client.put("/api/emergency-fund", json={"account_id": cash["id"], "monthly_override": 100_000})
    assert r.status_code == 422  # money saved: take it out first
    client.post(f"/api/piggy-banks/{pid}/events", json={"amount": -1_000})
    e = _setup(client, cash, monthly_override=100_000)
    assert e["piggy"]["id"] == pid and e["piggy"]["account"]["name"] == "Wallet"
    assert client.delete("/api/emergency-fund").status_code == 204
    assert client.get("/api/emergency-fund").json()["configured"] is False
    assert client.get("/api/piggy-banks").json() == []
    # deleting the emergency piggy bank directly also switches the fund off; setting up again works
    e = _setup(client, bank, monthly_override=100_000)
    client.delete(f"/api/piggy-banks/{e['piggy']['id']}")
    assert client.get("/api/emergency-fund").json()["configured"] is False
    assert _setup(client, bank)["configured"] is True


def test_history_starts_at_first_transaction(client, bank):
    spend(client, bank, 1_000, category_id=cat_id(client, "Rent"), date=month_day(2))
    h = essential_history_via_db(6)
    assert [m.month for m in h] == [add_months(THIS_MONTH, -2).strftime("%Y-%m"), add_months(THIS_MONTH, -1).strftime("%Y-%m")]


def essential_history_via_db(months: int):
    from app.db import SessionLocal

    with SessionLocal() as db:
        return essential_history(db, months)


def test_migration_marks_existing_starter_categories():
    backend = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "MONEYMAP_DATA_DIR": d}
        run = lambda *a: subprocess.run([sys.executable, "-m", "alembic", *a], cwd=backend, env=env,  # noqa: E731
                                        capture_output=True, text=True)
        assert run("upgrade", "0008_f8_piggy_banks").returncode == 0
        db = sqlite3.connect(Path(d) / "moneymap.db")
        db.executescript("INSERT INTO category (name, kind, icon, color) VALUES "
                         "('Rent', 'expense', 'key', 'indigo'), ('Dining', 'expense', 'x', 'coral'), "
                         "('Taxes', 'income', 'x', 'slate');")
        db.commit()
        db.close()
        assert run("upgrade", "head").returncode == 0
        db = sqlite3.connect(Path(d) / "moneymap.db")
        assert dict(db.execute("SELECT name, essential FROM category").fetchall()) == {"Rent": 1, "Dining": 0, "Taxes": 0}
        db.close()

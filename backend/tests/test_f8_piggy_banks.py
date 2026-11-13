"""F8: piggy banks — savings goals inside a bank or cash account."""

from datetime import date

from app.core.dates import add_months
from app.modules.piggybanks.router import monthly_needed

from .helpers import spend

TODAY = date.today()


def _piggy(client, account, name="Trip", target=6_000_000, **extra):
    r = client.post("/api/piggy-banks", json={"name": name, "account_id": account["id"], "target_amount": target, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_piggy_banks_need_login(anon):
    assert anon.get("/api/piggy-banks").status_code == 401


def test_only_bank_or_cash_accounts(client, bank):
    payee = spend(client, bank, 100)["destination"]
    r = client.post("/api/piggy-banks", json={"name": "Bad", "account_id": payee["id"], "target_amount": 100})
    assert r.status_code == 422
    assert client.post("/api/piggy-banks", json={"name": "Bad", "account_id": 9999, "target_amount": 100}).status_code == 422
    assert client.post("/api/piggy-banks", json={"name": " ", "account_id": bank["id"], "target_amount": 100}).status_code == 422
    assert client.post("/api/piggy-banks", json={"name": "X", "account_id": bank["id"], "target_amount": 0}).status_code == 422
    cash = client.post("/api/accounts", json={"name": "Wallet", "type": "cash", "opening_balance": 50_000}).json()
    assert _piggy(client, cash, name="Gift")["account"]["name"] == "Wallet"


def test_set_aside_limits(client, bank):
    # bank has ₹1,00,000
    p = _piggy(client, bank, "Trip", 6_000_000)
    q = _piggy(client, bank, "Laptop", 9_000_000)
    out = client.post(f"/api/piggy-banks/{p['id']}/events", json={"amount": 6_000_000}).json()
    assert (out["saved"], out["account_balance"], out["account_available"]) == (6_000_000, 10_000_000, 4_000_000)
    # only ₹40,000 left that isn't set aside
    r = client.post(f"/api/piggy-banks/{q['id']}/events", json={"amount": 5_000_000})
    assert r.status_code == 422 and "₹40,000.00" in r.json()["detail"]  # Indian digit grouping
    assert client.post(f"/api/piggy-banks/{q['id']}/events", json={"amount": 4_000_000}).json()["account_available"] == 0
    # can't take out more than is saved, or zero
    assert client.post(f"/api/piggy-banks/{p['id']}/events", json={"amount": -7_000_000}).status_code == 422
    assert client.post(f"/api/piggy-banks/{p['id']}/events", json={"amount": 0}).status_code == 422
    out = client.post(f"/api/piggy-banks/{p['id']}/events", json={"amount": -1_000_000, "note": " deposit "}).json()
    assert out["saved"] == 5_000_000
    events = client.get(f"/api/piggy-banks/{p['id']}/events").json()
    assert [(e["amount"], e["note"]) for e in events] == [(-1_000_000, "deposit"), (6_000_000, None)]


def test_spending_reduces_what_is_available(client, bank):
    p = _piggy(client, bank, "Trip", 6_000_000)
    client.post(f"/api/piggy-banks/{p['id']}/events", json={"amount": 6_000_000})
    spend(client, bank, 3_000_000)  # spend ₹30,000 from the account
    listed = client.get("/api/piggy-banks").json()[0]
    assert (listed["account_balance"], listed["account_available"]) == (7_000_000, 1_000_000)


def test_monthly_needed():
    assert monthly_needed(400_000, 0, add_months(TODAY, 4), TODAY) == 100_000
    assert monthly_needed(100_000, 0, add_months(TODAY, 3), TODAY) == 33_334  # rounded up
    assert monthly_needed(400_000, 100_000, TODAY, TODAY) == 300_000  # date reached: the whole rest
    assert monthly_needed(400_000, 400_000, add_months(TODAY, 4), TODAY) is None  # target reached
    assert monthly_needed(400_000, 0, None, TODAY) is None


def test_edit_and_delete(client, bank):
    p = _piggy(client, bank, "Trip", 400_000, target_date=add_months(TODAY, 4).isoformat())
    assert p["monthly_needed"] == 100_000
    r = client.patch(f"/api/piggy-banks/{p['id']}", json={"name": " Goa trip ", "target_date": None, "notes": "Dec"}).json()
    assert (r["name"], r["target_date"], r["monthly_needed"], r["notes"]) == ("Goa trip", None, None, "Dec")
    assert client.patch(f"/api/piggy-banks/{p['id']}", json={"name": "  "}).status_code == 422
    # moving to another account only while nothing is saved
    cash = client.post("/api/accounts", json={"name": "Wallet", "type": "cash", "opening_balance": 900_000}).json()
    client.post(f"/api/piggy-banks/{p['id']}/events", json={"amount": 1_000})
    assert client.patch(f"/api/piggy-banks/{p['id']}", json={"account_id": cash["id"]}).status_code == 422
    client.post(f"/api/piggy-banks/{p['id']}/events", json={"amount": -1_000})
    assert client.patch(f"/api/piggy-banks/{p['id']}", json={"account_id": cash["id"]}).json()["account"]["name"] == "Wallet"
    assert client.delete(f"/api/piggy-banks/{p['id']}").status_code == 204
    assert client.get("/api/piggy-banks").json() == []
    assert client.delete(f"/api/piggy-banks/{p['id']}").status_code == 404


def test_account_with_piggy_bank_cant_be_deleted(client):
    a = client.post("/api/accounts", json={"name": "Savings", "type": "asset", "opening_balance": 100}).json()
    p = _piggy(client, a, "Trip", 1_000)
    r = client.delete(f"/api/accounts/{a['id']}")
    assert r.status_code == 409 and "piggy bank" in r.json()["detail"]
    client.delete(f"/api/piggy-banks/{p['id']}")
    assert client.delete(f"/api/accounts/{a['id']}").status_code == 204

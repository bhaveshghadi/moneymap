"""F2: accounts and balances."""
from .helpers import TODAY, balance, cat_id, spend  # noqa: F401


def test_accounts_crud_rules(client, bank):
    assert client.post("/api/accounts", json={"name": "bank", "type": "asset"}).status_code == 409
    assert client.post("/api/accounts", json={"name": "Bank", "type": "cash"}).status_code == 201  # other type is fine
    # expense/revenue accounts never get an opening balance
    e = client.post("/api/accounts", json={"name": "Shop", "type": "expense", "opening_balance": 500}).json()
    assert e["opening_balance"] == 0
    # bank ↔ cash keeps transactions; expense can't switch
    spend(client, bank, 1_000)
    r = client.patch(f"/api/accounts/{bank['id']}", json={"type": "cash"})
    assert r.status_code == 409  # a cash account named "Bank" already exists
    r = client.patch(f"/api/accounts/{bank['id']}", json={"type": "cash", "name": "Bank wallet"})
    assert r.status_code == 200 and r.json()["type"] == "cash" and r.json()["balance"] == 10_000_000 - 1_000
    assert client.patch(f"/api/accounts/{e['id']}", json={"type": "asset"}).status_code == 422
    assert client.patch(f"/api/accounts/{bank['id']}", json={"type": "asset"}).json()["type"] == "asset"
    # rename, deactivate
    r = client.patch(f"/api/accounts/{bank['id']}", json={"name": " HDFC ", "active": False})
    assert r.json()["name"] == "HDFC" and r.json()["active"] is False
    # in use → can't delete; unused → can
    assert client.delete(f"/api/accounts/{bank['id']}").status_code == 409
    assert client.delete(f"/api/accounts/{e['id']}").status_code == 204
    types = {a["type"] for a in client.get("/api/accounts", params={"type": ["asset", "cash"]}).json()}
    assert types == {"asset", "cash"}


def test_no_liability_accounts_in_this_release(client):
    r = client.post("/api/accounts", json={"name": "HDFC card", "type": "liability"})
    assert r.status_code == 422
    assert "liability_kind" not in client.post("/api/accounts", json={"name": "SBI", "type": "asset"}).json()

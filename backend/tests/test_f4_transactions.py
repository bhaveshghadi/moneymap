"""F4: transactions."""
from .helpers import TODAY, balance, cat_id, spend  # noqa: F401


def test_expense_creates_payee_and_moves_balance(client, bank):
    t = spend(client, bank, 45_000, payee="Swiggy", category_id=cat_id(client, "Food Delivery"), tags=["work", " work "])
    assert t["destination"]["type"] == "expense" and t["destination"]["name"] == "Swiggy"
    assert t["category"]["name"] == "Food Delivery"
    assert t["tags"] == ["work"]
    assert balance(client, bank["id"]) == 10_000_000 - 45_000
    # same payee, different case → same expense account, total spent there
    t2 = spend(client, bank, 5_000, payee="swiggy")
    assert t2["destination"]["id"] == t["destination"]["id"]
    assert balance(client, t["destination"]["id"]) == 50_000


def test_income_and_transfer(client, bank):
    cash = client.post("/api/accounts", json={"name": "Wallet", "type": "cash"}).json()
    r = client.post("/api/transactions", json={"type": "deposit", "date": TODAY, "amount": 5_000_000,
                                               "description": "Salary", "source_name": "Employer", "destination_id": bank["id"],
                                               "category_id": cat_id(client, "Salary")})
    assert r.status_code == 201 and r.json()["source"]["type"] == "revenue"
    r = client.post("/api/transactions", json={"type": "transfer", "date": TODAY, "amount": 100_00, "description": "ATM",
                                               "source_id": bank["id"], "destination_id": cash["id"],
                                               "category_id": cat_id(client, "Shopping")})
    assert r.status_code == 201
    assert r.json()["category"] is None  # transfers stay uncategorised
    assert balance(client, cash["id"]) == 100_00
    # cash can go below zero (overdrawn)
    spend(client, cash, 150_00)
    assert balance(client, cash["id"]) == -50_00
    assert balance(client, bank["id"]) == 10_000_000 + 5_000_000 - 100_00


def test_transaction_validation(client, bank):
    base = {"type": "withdrawal", "date": TODAY, "amount": 100, "description": "x", "source_id": bank["id"]}
    assert client.post("/api/transactions", json=base).status_code == 422  # no payee
    assert client.post("/api/transactions", json={**base, "destination_name": "A", "amount": 0}).status_code == 422
    assert client.post("/api/transactions", json={**base, "destination_name": "A", "description": "  "}).status_code == 422
    assert client.post("/api/transactions", json={**base, "destination_name": "A", "category_id": 99999}).status_code == 422
    # can't pay from an expense account
    payee = spend(client, bank, 100)["destination"]
    assert client.post("/api/transactions", json={**base, "source_id": payee["id"], "destination_name": "B"}).status_code == 422
    same = {"type": "transfer", "date": TODAY, "amount": 100, "description": "x", "source_id": bank["id"], "destination_id": bank["id"]}
    assert client.post("/api/transactions", json=same).status_code == 422


def test_edit_and_delete_transaction(client, bank):
    t = spend(client, bank, 1_000, tags=["a"])
    body = {"type": "withdrawal", "date": "2026-11-01", "amount": 2_500, "description": "Dinner",
            "source_id": bank["id"], "destination_name": "Zomato", "tags": [], "notes": " late "}
    r = client.put(f"/api/transactions/{t['id']}", json=body)
    assert r.status_code == 200
    out = r.json()
    assert (out["amount"], out["description"], out["destination"]["name"], out["tags"], out["notes"]) == (
        2_500, "Dinner", "Zomato", [], "late")
    assert balance(client, bank["id"]) == 10_000_000 - 2_500
    assert client.delete(f"/api/transactions/{t['id']}").status_code == 204
    assert client.get(f"/api/transactions/{t['id']}").status_code == 404
    assert balance(client, bank["id"]) == 10_000_000


def test_list_filters_and_totals(client, bank):
    food = cat_id(client, "Groceries")
    spend(client, bank, 1_000, payee="BigBasket", desc="Veg", category_id=food, tags=["home"], date="2026-10-05")
    spend(client, bank, 2_000, payee="Amazon", desc="Cable")
    client.post("/api/transactions", json={"type": "deposit", "date": TODAY, "amount": 9_000, "description": "Refund",
                                           "source_name": "Amazon", "destination_id": bank["id"]})
    page = client.get("/api/transactions").json()
    assert page["total"] == 3 and page["sum_out"] == 3_000 and page["sum_in"] == 9_000
    assert [t["description"] for t in page["items"]] == ["Refund", "Cable", "Veg"]  # newest first
    get = lambda **p: client.get("/api/transactions", params=p).json()  # noqa: E731
    assert get(type="withdrawal")["total"] == 2
    assert get(category_id=food)["total"] == 1
    assert get(uncategorised=True)["total"] == 2
    assert get(tag="HOME")["total"] == 1
    assert get(date_from="2026-11-01")["total"] == 2
    assert get(date_to="2026-10-31")["total"] == 1
    assert get(q="amazon")["total"] == 2  # payee name, either side
    assert get(q="amazon cable")["total"] == 1  # all words must match
    assert get(limit=1, offset=1)["items"][0]["description"] == "Cable"


def test_category_must_fit_the_type(client, bank):
    salary = cat_id(client, "Salary")
    r = client.post("/api/transactions", json={"type": "withdrawal", "date": TODAY, "amount": 100, "description": "x",
                                               "source_id": bank["id"], "destination_name": "Shop", "category_id": salary})
    assert r.status_code == 422 and "income category" in r.json()["detail"]


def test_text_search_treats_wildcards_literally(client, bank):
    spend(client, bank, 100, desc="100% cotton")
    spend(client, bank, 100, desc="plain")
    assert client.get("/api/transactions", params={"q": "%"}).json()["total"] == 1
    assert client.get("/api/transactions", params={"q": "_"}).json()["total"] == 0

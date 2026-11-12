"""F5: Overview dashboard."""


def _acct(client, name, type_, opening=0, **extra):
    return client.post("/api/accounts", json={"name": name, "type": type_, "opening_balance": opening, **extra}).json()


def _cat(client, name):
    return next(c["id"] for c in client.get("/api/categories").json() if c["name"] == name)


def _txn(client, **body):
    r = client.post("/api/transactions", json={"description": "x", **body})
    assert r.status_code == 201, r.text
    return r.json()


def test_overview_empty(client):
    o = client.get("/api/overview?month=2026-11").json()
    assert o["month"] == "2026-11"
    assert (o["net_worth"], o["income"], o["spending"], o["transaction_count"]) == (0, 0, 0, 0)
    assert o["accounts"] == [] and o["by_category"] == [] and o["recent"] == []


def test_overview_totals_and_categories(client):
    bank = _acct(client, "Bank", "asset", 10_000_000)
    wallet = _acct(client, "Wallet", "cash", 50_000)
    gone = _acct(client, "Old bank", "asset", 999_00)
    client.patch(f"/api/accounts/{gone['id']}", json={"active": False})
    food, rent = _cat(client, "Food Delivery"), _cat(client, "Rent")

    _txn(client, type="deposit", date="2026-11-01", amount=500_000, source_name="Employer", destination_id=bank["id"])
    _txn(client, type="withdrawal", date="2026-11-03", amount=30_000, source_id=bank["id"], destination_name="Landlord", category_id=rent)
    _txn(client, type="withdrawal", date="2026-11-05", amount=1_000, source_id=wallet["id"], destination_name="Swiggy", category_id=food)
    _txn(client, type="withdrawal", date="2026-11-06", amount=2_500, source_id=bank["id"], destination_name="Swiggy", category_id=food)
    _txn(client, type="withdrawal", date="2026-11-07", amount=700, source_id=bank["id"], destination_name="Shop")  # uncategorised
    _txn(client, type="withdrawal", date="2026-10-30", amount=9_999, source_id=bank["id"], destination_name="Shop", category_id=food)
    # transfers don't count as income or spending
    _txn(client, type="transfer", date="2026-11-08", amount=5_000, source_id=bank["id"], destination_id=wallet["id"])

    o = client.get("/api/overview?month=2026-11").json()
    assert (o["income"], o["spending"]) == (500_000, 30_000 + 1_000 + 2_500 + 700)
    assert [(c["name"], c["amount"]) for c in o["by_category"]] == [("Rent", 30_000), ("Food Delivery", 3_500), ("Uncategorised", 700)]
    assert o["by_category"][-1]["id"] is None
    # inactive accounts are left out of the balances
    assert {a["name"] for a in o["accounts"]} == {"Bank", "Wallet"}
    bank_now = 10_000_000 + 500_000 - 30_000 - 2_500 - 700 - 9_999 - 5_000
    wallet_now = 50_000 - 1_000 + 5_000
    assert o["net_worth"] == bank_now + wallet_now
    assert o["transaction_count"] == 7
    assert [t["date"] for t in o["recent"]][:2] == ["2026-11-08", "2026-11-07"]

    october = client.get("/api/overview?month=2026-10").json()
    assert (october["income"], october["spending"]) == (0, 9_999)
    assert october["net_worth"] == o["net_worth"]  # balances are "right now", not per month


def test_overview_rejects_bad_month(client):
    assert client.get("/api/overview?month=2026-13").status_code == 422
    assert client.get("/api/overview?month=nope").status_code == 422

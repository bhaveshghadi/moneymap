TODAY = "2026-11-10"


def cat_id(client, name):
    return next(c["id"] for c in client.get("/api/categories").json() if c["name"] == name)


def spend(client, bank, amount, payee="Swiggy", desc="Lunch", **extra):
    body = {"type": "withdrawal", "date": extra.pop("date", TODAY), "amount": amount, "description": desc,
            "source_id": bank["id"], "destination_name": payee, **extra}
    r = client.post("/api/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def balance(client, account_id):
    return client.get(f"/api/accounts/{account_id}").json()["balance"]

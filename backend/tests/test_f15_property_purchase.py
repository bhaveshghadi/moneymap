"""Property bought in parts: agreed price vs paid, the plan for the balance, status, costs on top,
net worth (only what's paid until registered) and a goal for the balance. Amounts made up."""

from datetime import date, timedelta

LAKH = 100_000 * 100
TODAY = date.today()


def _plot(client, paid=10 * LAKH):
    r = client.post("/api/investments", json={"kind": "property", "name": "Village plot", "amount": paid})
    assert r.status_code == 201, r.text
    return r.json()


def _deal(client, pid, **extra):
    body = {
        "price": 20 * LAKH,
        "size": "2 guntha",
        "location": "Village",
        "seller": "Seller",
        "agreement_date": (TODAY - timedelta(days=90)).isoformat(),
        "status": "registration_pending",
        "plan": [
            {"due_date": (TODAY - timedelta(days=5)).isoformat(), "amount": 5 * LAKH},
            {"due_date": (TODAY + timedelta(days=60)).isoformat(), "amount": 5 * LAKH, "note": "On registration"},
        ],
        **extra,
    }
    r = client.put(f"/api/investments/{pid}/property", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_paid_vs_balance_and_plan(client, bank):
    plot = _plot(client)
    d = _deal(client, plot["id"])
    p = d["property"]
    assert (p["price_paid"], p["balance"], p["unplanned"]) == (10 * LAKH, 10 * LAKH, 0)
    assert [x["status"] for x in p["plan"]] == ["overdue", "due"]
    # not registered: it counts as what's been paid
    assert d["value"] == d["invested"] == 10 * LAKH
    assert d["next_due"]["what"] == "balance" and d["next_due"]["overdue"] is True

    # pay the first instalment from the bank (a transfer, not spending)
    d = client.post(f"/api/investments/{plot['id']}/move", json={
        "direction": "in", "amount": 5 * LAKH, "date": TODAY.isoformat(), "bank_id": bank["id"],
    }).json()  # fmt: skip
    p = d["property"]
    assert [x["status"] for x in p["plan"]] == ["paid", "due"] and p["balance"] == 5 * LAKH
    assert d["value"] == 15 * LAKH
    assert client.get("/api/overview").json()["spending"] == 0
    dues = client.get("/api/investments/dues", params={"days": 90}).json()
    assert [(x["what"], x["amount"]) for x in dues] == [("balance", 5 * LAKH)]


def test_costs_on_top_and_registration(client, bank):
    plot = _plot(client)
    _deal(client, plot["id"])
    d = client.post(f"/api/investments/{plot['id']}/property/costs", json={
        "kind": "stamp_duty", "amount": 1 * LAKH, "date": TODAY.isoformat(), "bank_id": bank["id"],
    }).json()  # fmt: skip
    p = d["property"]
    assert (p["price_paid"], p["costs_total"], p["total_cost"]) == (10 * LAKH, 1 * LAKH, 11 * LAKH)
    assert d["invested"] == 11 * LAKH and d["value"] == 11 * LAKH  # paid so far, costs included
    # a cost paid before tracking: on top, but no money moves
    d = client.post(f"/api/investments/{plot['id']}/property/costs", json={
        "kind": "broker", "amount": 20_000 * 100, "date": TODAY.isoformat(),
    }).json()  # fmt: skip
    assert d["property"]["costs_total"] == 1 * LAKH + 20_000 * 100 and d["invested"] == 11 * LAKH

    assert client.put(f"/api/investments/{plot['id']}/property", json={"status": "registered"}).status_code == 422
    d = _deal(client, plot["id"], status="registered", registered_on=TODAY.isoformat())
    assert d["property"]["status"] == "registered" and d["value"] == 20 * LAKH  # the price, once it's yours
    client.patch(f"/api/investments/{plot['id']}", json={"current_value": 25 * LAKH})
    assert client.get(f"/api/investments/{plot['id']}").json()["value"] == 25 * LAKH

    # removing a cost paid through MoneyMap removes its payment too
    stamp = next(c for c in d["property"]["costs"] if c["kind"] == "stamp_duty")
    d = client.delete(f"/api/investments/{plot['id']}/property/costs/{stamp['id']}").json()
    assert d["invested"] == 10 * LAKH and all(c["kind"] != "stamp_duty" for c in d["property"]["costs"])


def test_net_worth_counts_only_what_is_paid(client, bank):
    plot = _plot(client)
    client.patch(f"/api/investments/{plot['id']}", json={"current_value": 30 * LAKH})
    _deal(client, plot["id"])  # not registered
    assert client.get("/api/investments/summary").json()["value"] == 10 * LAKH


def test_goal_for_the_balance(client, bank):
    plot = _plot(client)
    assert (
        client.post(f"/api/investments/{plot['id']}/property/goal", json={"account_id": bank["id"]}).status_code == 422
    )
    _deal(client, plot["id"])
    d = client.post(f"/api/investments/{plot['id']}/property/goal", json={"account_id": bank["id"]}).json()
    goal = next(g for g in client.get("/api/piggy-banks").json() if g["id"] == d["property"]["goal_id"])
    assert goal["target_amount"] == 10 * LAKH and goal["target_date"] == (TODAY + timedelta(days=60)).isoformat()
    # the goal follows the balance
    client.post(f"/api/investments/{plot['id']}/move", json={
        "direction": "in", "amount": 4 * LAKH, "date": TODAY.isoformat(), "bank_id": bank["id"],
    })  # fmt: skip
    client.get(f"/api/investments/{plot['id']}")
    goal = next(g for g in client.get("/api/piggy-banks").json() if g["id"] == d["property"]["goal_id"])
    assert goal["target_amount"] == 6 * LAKH


def test_only_property(client, bank):
    fd = client.post("/api/investments", json={"kind": "other", "name": "Something", "amount": 100}).json()
    assert client.put(f"/api/investments/{fd['id']}/property", json={"price": 100}).status_code == 422


def test_property_with_nothing_paid_yet(client, bank):
    r = client.post("/api/investments", json={"kind": "property", "name": "Booked plot"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert (d["invested"], d["value"], d["start_date"]) == (0, 0, None)
    d = client.put(f"/api/investments/{d['id']}/property", json={"price": 20 * LAKH, "status": "booked"}).json()
    assert d["property"]["balance"] == 20 * LAKH

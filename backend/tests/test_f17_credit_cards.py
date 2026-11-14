"""Credit cards: card accounts, billing cycles (statement day, due date), statuses and payments."""

from datetime import date

from app.modules.cards.cycles import Rule, build_cycles, due_date, statement_dates

from .helpers import cat_id

R12 = [Rule(date(2000, 1, 1), 12, "days_after", 20)]


# ---------------------------------------------------------------- maths


def test_due_date_modes():
    assert due_date(date(2026, 11, 12), Rule(date(2000, 1, 1), 12, "days_after", 20)) == date(2026, 12, 2)
    # fixed day: the first such day after the statement
    assert due_date(date(2026, 11, 12), Rule(date(2000, 1, 1), 12, "fixed_day", 2)) == date(2026, 12, 2)
    assert due_date(date(2026, 11, 5), Rule(date(2000, 1, 1), 5, "fixed_day", 28)) == date(2026, 11, 28)
    assert due_date(date(2027, 1, 31), Rule(date(2000, 1, 1), 31, "fixed_day", 30)) == date(2027, 2, 28)


def test_statement_day_31_uses_month_end():
    rules = [Rule(date(2000, 1, 1), 31, "days_after", 18)]
    assert statement_dates(rules, date(2027, 1, 1), date(2027, 4, 30)) == [
        date(2027, 1, 31),
        date(2027, 2, 28),
        date(2027, 3, 31),
        date(2027, 4, 30),
    ]


def test_cycle_change_keeps_old_dates():
    rules = [R12[0], Rule(date(2026, 10, 13), 25, "days_after", 20)]  # from the cycle after 12 Oct: the 25th
    assert statement_dates(rules, date(2026, 8, 1), date(2026, 12, 31)) == [
        date(2026, 8, 12),
        date(2026, 9, 12),
        date(2026, 10, 12),
        date(2026, 10, 25),
        date(2026, 11, 25),
        date(2026, 12, 25),
    ]


def test_cycles_statuses_and_fifo_payments():
    moves = [
        (date(2026, 9, 20), -1_000_000),  # spent in the cycle 13 Sep - 12 Oct
        (date(2026, 10, 5), -500_000),
        (date(2026, 10, 25), 1_500_000),  # paid in full before the 1 Nov due date
        (date(2026, 10, 20), -300_000),  # next cycle
    ]
    cycles = build_cycles(R12, 0, date(2026, 9, 15), moves, date(2026, 11, 14), 5)
    assert [c.statement_date for c in cycles] == [date(2026, 10, 12), date(2026, 11, 12), date(2026, 12, 12)]
    octo, nov, dec = cycles
    assert (octo.start, octo.due_date) == (date(2026, 9, 13), date(2026, 11, 1))
    assert (octo.spent, octo.total_due, octo.min_due, octo.status, octo.paid_on) == (
        1_500_000,
        1_500_000,
        75_000,
        "paid",
        date(2026, 10, 25),
    )
    assert (nov.total_due, nov.status, nov.due_date) == (300_000, "billed", date(2026, 12, 2))
    assert nov.min_due == 20_000  # 5% is ₹150 -> the ₹200 floor
    assert dec.status == "unbilled"


def test_overdue_and_minimum_paid():
    moves = [(date(2026, 9, 20), -1_000_000), (date(2026, 10, 30), 60_000)]
    c = build_cycles(R12, 0, date(2026, 9, 13), moves, date(2026, 11, 14), 5)
    octo = next(x for x in c if x.statement_date == date(2026, 10, 12))
    assert (octo.status, octo.paid, octo.min_paid) == ("overdue", 60_000, True)


def test_partly_paid_and_late_payment_clears_it():
    moves = [(date(2026, 10, 1), -1_000_000), (date(2026, 10, 20), 400_000)]
    c = build_cycles(R12, 0, date(2026, 10, 1), moves, date(2026, 10, 25), 5)
    assert (c[0].status, c[0].paid) == ("partly_paid", 400_000)
    moves.append((date(2026, 11, 20), 600_000))  # paid after the due date (1 Nov)
    c = build_cycles(R12, 0, date(2026, 10, 1), moves, date(2026, 11, 25), 5)
    assert (c[0].status, c[0].paid_on) == ("paid", date(2026, 11, 20))


# ---------------------------------------------------------------- API


def _card(client, **extra):
    body = {
        "name": "HDFC Millennia",
        "bank": "HDFC",
        "last4": "4321",
        "network": "visa",
        "credit_limit": 20_000_000,
        "statement_day": 12,
        "due_mode": "days_after",
        "due_value": 20,
        **extra,
    }
    r = client.post("/api/cards", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _spend(client, card_id, amount, d, cat=None):
    body = {"type": "withdrawal", "date": d, "amount": amount, "description": "Shop", "source_id": card_id,
            "destination_name": "Amazon", "category_id": cat}
    r = client.post("/api/transactions", json=body)
    assert r.status_code == 201, r.text


def _pay(client, bank_id, card_id, amount, d):
    body = {"type": "transfer", "date": d, "amount": amount, "description": "Card bill", "source_id": bank_id,
            "destination_id": card_id}
    r = client.post("/api/transactions", json=body)
    assert r.status_code == 201, r.text


def test_needs_login(anon):
    assert anon.get("/api/cards").status_code == 401


def test_create_and_validate(client):
    c = _card(client, opening_owed=250_000)
    assert (c["name"], c["last4"], c["statement_day"], c["owed"], c["available"]) == (
        "HDFC Millennia",
        "4321",
        12,
        250_000,
        19_750_000,
    )
    assert c["current"]["status"] == "unbilled"
    assert client.post("/api/cards", json={"name": "X", "statement_day": 32}).status_code == 422
    assert client.post("/api/cards", json={"name": "X", "statement_day": 5, "last4": "12a4"}).status_code == 422
    bad_due = {"name": "X", "statement_day": 5, "due_mode": "fixed_day", "due_value": 40}
    assert client.post("/api/cards", json=bad_due).status_code == 422
    assert client.post("/api/cards", json={"name": "HDFC Millennia", "statement_day": 5}).status_code == 409
    # cards are made on the Credit cards page, not as plain accounts
    assert client.post("/api/accounts", json={"name": "C", "type": "credit_card"}).status_code == 422


def test_spend_pay_and_balances(client, bank):
    card = _card(client)
    food = cat_id(client, "Groceries")
    _spend(client, card["id"], 1_200_000, "2026-09-20", food)
    _pay(client, bank["id"], card["id"], 1_200_000, "2026-10-28")
    _spend(client, card["id"], 300_000, "2026-10-20", food)
    c = client.get(f"/api/cards/{card['id']}").json()
    assert c["owed"] == 300_000 and c["utilisation"] == 1.5
    by_sd = {x["statement_date"]: x for x in c["cycles"]}
    assert by_sd["2026-10-12"]["status"] == "paid"
    # a card spend is an expense (counted as spending); paying the bill is a transfer (not spending)
    page = client.get("/api/transactions", params={"type": "withdrawal"}).json()
    assert page["sum_out"] == 1_500_000
    accounts = {a["name"]: a["balance"] for a in client.get("/api/accounts").json()}
    assert accounts["Bank"] == 10_000_000 - 1_200_000 and accounts["HDFC Millennia"] == -300_000


def test_overview_net_worth_and_dues(client, bank):
    card = _card(client)
    _spend(client, card["id"], 500_000, date(date.today().year - 1, 1, 15).isoformat())  # long overdue
    o = client.get("/api/overview").json()
    assert o["cards_owed"] == 500_000 and o["net_worth"] == 10_000_000 - 500_000
    assert [(d["status"], d["amount"]) for d in o["card_dues"]] == [("overdue", 500_000)]


def test_change_statement_day_applies_from_next_cycle(client):
    card = _card(client, opening_date="2026-01-01")
    c = client.patch(f"/api/cards/{card['id']}", json={"statement_day": 25}).json()
    assert c["statement_day"] == 25
    dates = [x["statement_date"] for x in c["cycles"]]
    assert "2026-10-12" in dates  # already issued: kept
    assert c["current"]["statement_date"].endswith("-25")
    # changing it again before any new statement just replaces the pending rule
    c = client.patch(f"/api/cards/{card['id']}", json={"statement_day": 20}).json()
    assert c["current"]["statement_date"].endswith("-20") and "2026-10-12" in [x["statement_date"] for x in c["cycles"]]


def test_delete_rules(client, bank):
    card = _card(client)
    _spend(client, card["id"], 1000, "2026-10-01")
    assert client.delete(f"/api/cards/{card['id']}").status_code == 409
    assert client.delete(f"/api/accounts/{card['id']}").status_code == 422
    empty = _card(client, name="Spare")
    assert client.delete(f"/api/cards/{empty['id']}").status_code == 204
    assert client.get(f"/api/cards/{empty['id']}").status_code == 404

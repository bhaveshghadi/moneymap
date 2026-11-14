"""Card EMIs: purchase counted once in full; the conversion credit, monthly principal,
interest/GST and early closure; matching EMI rows when importing a card statement."""

from .helpers import cat_id
from .test_statement_import import add_email


def _card(client, **extra):
    body = {"name": "Amazon Pay", "last4": "3003", "statement_day": 18, "due_mode": "days_after", "due_value": 18,
            "credit_limit": 30_000_000, **extra}
    r = client.post("/api/cards", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _spend(client, card, amount, d, desc, cat=None):
    r = client.post("/api/transactions", json={"type": "withdrawal", "date": d, "amount": amount, "description": desc,
                                               "source_id": card["id"], "destination_name": desc.split()[0],
                                               "category_id": cat})
    assert r.status_code == 201, r.text
    return r.json()


def _emi(client, card, **body):
    r = client.post(f"/api/cards/{card['id']}/emis", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _spending(client):
    return client.get("/api/transactions", params={"type": "withdrawal"}).json()["sum_out"]


def test_converted_purchase(client):
    card = _card(client)
    buy = _spend(client, card, 3_493_400, "2026-07-15", "CROMA RETAIL MUMBAI", cat_id(client, "Electronics"))
    res = _emi(client, card, kind="converted", name="Croma", principal=3_493_400, tenure=6, start_date="2026-08-18",
               purchase_txn_id=buy["id"], converted_on="2026-07-20", interest_rate=15.99)
    e = res["emi"]
    assert (e["outstanding"], e["paid_count"], e["status"], e["finish_date"], e["next_date"]) == (
        3_493_400, 0, "active", "2027-01-18", "2026-08-18"
    )
    assert e["interest_rate"] == 15.99
    c = client.get(f"/api/cards/{card['id']}").json()
    # the debt moved off the card bill into the EMI, but it still uses up the limit
    assert (c["owed"], c["emi_outstanding"], c["available"], c["emi_count"]) == (0, 3_493_400, 30_000_000 - 3_493_400, 1)
    assert _spending(client) == 3_493_400  # counted once, in full, when bought
    o = client.get("/api/overview").json()
    assert o["cards_owed"] == 3_493_400


def test_checkout_emi_counts_the_purchase_once(client):
    card = _card(client)
    res = _emi(client, card, kind="checkout", name="Flipkart", principal=3_469_470, tenure=6, start_date="2026-08-20",
               purchase_date="2026-07-20", category_id=cat_id(client, "Electronics"), no_cost=True)
    e = res["emi"]
    assert (e["outstanding"], e["kind"], e["no_cost"]) == (3_469_470, "checkout", True)
    page = client.get("/api/transactions", params={"type": "withdrawal"}).json()
    assert page["sum_out"] == 3_469_470 and page["items"][0]["category"]["name"] == "Electronics"
    c = client.get(f"/api/cards/{card['id']}").json()
    assert (c["owed"], c["emi_outstanding"]) == (0, 3_469_470)  # nothing on the card bill yet


CARD_EMI_LINES = [
    "Credit Card Statement",
    "Card No: XXXX XXXX XXXX 3003",
    "Statement Date : 18/08/2026",
    "Date Transaction Details Amount",
    "20/07/2026 EMI CONVERSION CROMA RETAIL 34,934.00 CR",
    "18/08/2026 Principal Amount Amortization - <1/6>Croma Retail 5,822.33",
    "18/08/2026 Interest Amount Amortization - <1/6>Croma Retail 300.00",
    "18/08/2026 SGST-CI@9% 27.00",
    "18/08/2026 CGST-CI@9% 27.00",
    "10/08/2026 ZOMATO GURGAON 500.00",
]


def test_statement_rows_match_the_plan(client):
    card = _card(client)
    buy = _spend(client, card, 3_493_400, "2026-07-15", "CROMA RETAIL MUMBAI", cat_id(client, "Electronics"))
    plan = _emi(client, card, kind="converted", name="Croma Retail", principal=3_493_400, tenure=6,
                start_date="2026-08-18", purchase_txn_id=buy["id"], converted_on="2026-07-25")["emi"]
    att = add_email(CARD_EMI_LINES, mid="emi1", sender="ICICI <cards@icicibank.com>")
    d = client.post("/api/statements", json={"attachment_id": att, "password": "test-pdf-pass"}).json()
    rows = {r["description"][:12]: r for r in d["rows"]}
    conv = rows["EMI CONVERSI"]
    assert (conv["kind"], conv["status"]) == ("transfer", "duplicate")  # already recorded with the plan
    pr = rows["Principal Am"]
    assert (pr["kind"], pr["transfer_account_id"], pr["emi_id"], pr["status"]) == (
        "transfer", plan["account_id"], plan["id"], "ready"
    )
    assert pr["suggestion"] == "EMI instalment 1/6 · Croma Retail" and pr["flag"] is None
    fees = cat_id(client, "Card Fees & Interest")
    for key in ("Interest Amo", "SGST-CI@9%", "CGST-CI@9%"):
        assert rows[key]["emi_id"] == plan["id"] and rows[key]["category_id"] == fees
    client.patch(f"/api/statements/{d['id']}/rows/{rows['ZOMATO GURGA']['id']}", json={"leave_uncategorised": True})
    assert client.post(f"/api/statements/{d['id']}/import").json()["imported"] == 5

    e = client.get(f"/api/cards/{card['id']}/emis").json()[0]
    assert (e["paid_count"], e["outstanding"], e["principal_paid"], e["interest_paid"], e["next_date"]) == (
        1, 3_493_400 - 582_233, 582_233, 35_400, "2026-09-18"
    )
    # spending: the purchase once + interest/GST + the Zomato order — not the principal
    assert _spending(client) == 3_493_400 + 35_400 + 50_000
    c = client.get(f"/api/cards/{card['id']}").json()
    # this month's principal is on the card bill; the rest is still in the EMI
    assert c["owed"] == 582_233 + 35_400 + 50_000 and c["emi_outstanding"] == 3_493_400 - 582_233


def test_existing_plan_links_past_rows(client):
    card = _card(client)
    _spend(client, card, 578_245, "2026-09-20", "Principal Amount Amortization - <3/6>Flipkart Internet PVT L")
    _spend(client, card, 31_442, "2026-09-20", "Interest Amount Amortization - <3/6>Flipkart Internet PVT LT")
    _spend(client, card, 2_830, "2026-09-20", "SGST-CI@9%")
    _spend(client, card, 2_830, "2026-09-20", "CGST-CI@9%")
    _spend(client, card, 69_000, "2026-09-20", "AMAZON PAY IN UTILITY")
    res = _emi(client, card, kind="existing", name="Flipkart", principal=3_469_470, tenure=6, start_date="2026-07-20",
               outstanding=1_734_735, instalment=609_687)
    assert (res["linked_instalments"], res["linked_charges"]) == (1, 3)
    e = res["emi"]
    assert (e["outstanding"], e["paid_count"], e["interest_paid"], e["next_date"]) == (1_734_735, 3, 37_102, "2026-10-20")
    # the instalment is no longer spending; the Amazon spend is untouched
    assert _spending(client) == 31_442 + 2_830 + 2_830 + 69_000


def test_close_early_and_delete(client):
    card = _card(client)
    buy = _spend(client, card, 1_200_000, "2026-09-01", "PHONE SHOP")
    e = _emi(client, card, kind="converted", name="Phone shop", principal=1_200_000, tenure=3, start_date="2026-10-18",
             purchase_txn_id=buy["id"], converted_on="2026-09-05")["emi"]
    assert client.get(f"/api/cards/{card['id']}").json()["owed"] == 0
    closed = client.post(f"/api/cards/{card['id']}/emis/{e['id']}/close", json={"date": "2026-10-01"}).json()
    assert (closed["status"], closed["outstanding"], closed["closed_on"]) == ("closed", 0, "2026-10-01")
    assert client.get(f"/api/cards/{card['id']}").json()["owed"] == 1_200_000  # back on the card bill

    buy2 = _spend(client, card, 600_000, "2026-09-02", "TV SHOP")
    e2 = _emi(client, card, kind="converted", name="TV shop", principal=600_000, tenure=3, start_date="2026-10-18",
              purchase_txn_id=buy2["id"])["emi"]
    assert client.delete(f"/api/cards/{card['id']}/emis/{e2['id']}").status_code == 204
    c = client.get(f"/api/cards/{card['id']}").json()
    assert c["owed"] == 1_800_000 and len(c["emis"]) == 1


def test_validation(client):
    card = _card(client)
    other = _card(client, name="Other", last4="1111")
    buy = _spend(client, other, 1000, "2026-09-01", "X")
    bad = client.post(f"/api/cards/{card['id']}/emis", json={"kind": "converted", "name": "X", "principal": 1000,
                                                             "tenure": 3, "start_date": "2026-10-01",
                                                             "purchase_txn_id": buy["id"]})
    assert bad.status_code == 422  # a purchase on another card
    assert client.post(f"/api/cards/{card['id']}/emis", json={"kind": "existing", "name": "X", "principal": 1000,
                                                              "tenure": 3, "start_date": "2026-10-01"}).status_code == 422
    assert client.post("/api/accounts", json={"name": "E", "type": "emi_plan"}).status_code == 422


def test_past_rows_of_another_purchase_are_not_moved(client):
    card = _card(client)
    _spend(client, card, 578_245, "2026-09-20", "Principal Amount Amortization - <3/6>Flipkart Internet PVT L")
    buy = _spend(client, card, 3_493_400, "2026-10-25", "PHONE STORE")
    res = _emi(client, card, kind="converted", name="Phone store", principal=3_493_400, tenure=6,
               start_date="2026-11-18", purchase_txn_id=buy["id"])
    assert res["linked_instalments"] == 0 and res["emi"]["paid_count"] == 0

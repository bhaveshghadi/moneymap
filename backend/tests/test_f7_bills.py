"""F7: bills — schedule maths, status, auto-matching new expenses, filters, Overview card."""

from datetime import date, datetime, timedelta

from app.models import Bill
from app.modules.bills.schedule import bill_state, due_index_on_or_before, monthly_cost, nth_due

from .helpers import spend

TODAY = date.today()


def make_bill(**kw) -> Bill:
    defaults = dict(name="B", amount_min=100, amount_max=100, first_due=date(2026, 1, 31), repeat="monthly",
                    skip=0, active=True, created_at=datetime(2025, 1, 1))
    defaults.update(kw)
    return Bill(**defaults)


# ---------------------------------------------------------------- schedule maths


def test_monthly_schedule_keeps_the_day():
    b = make_bill()
    assert [nth_due(b, k) for k in range(4)] == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]
    assert due_index_on_or_before(b, date(2026, 3, 30)) == 1
    assert due_index_on_or_before(b, date(2026, 3, 31)) == 2
    assert due_index_on_or_before(b, date(2025, 12, 1)) == -1


def test_weekly_quarterly_and_skip():
    every_2_weeks = make_bill(first_due=date(2026, 11, 2), repeat="weekly", skip=1)
    assert nth_due(every_2_weeks, 2) == date(2026, 11, 30)
    quarterly = make_bill(first_due=date(2026, 1, 15), repeat="quarterly")
    assert [nth_due(quarterly, k) for k in range(3)] == [date(2026, 1, 15), date(2026, 4, 15), date(2026, 7, 15)]
    assert monthly_cost(make_bill(amount_min=1200, amount_max=1200, repeat="yearly")) == 100
    assert monthly_cost(make_bill(amount_min=300, amount_max=300, repeat="quarterly")) == 100


def test_bill_status():
    b = make_bill(first_due=date(2026, 1, 10))
    # paid for 10 Nov -> paid, next due 10 Dec
    st = bill_state(b, [date(2026, 11, 9)], today=date(2026, 11, 20))
    assert (st.status, st.next_due) == ("paid", date(2026, 12, 10))
    # nothing paid for 10 Nov -> overdue
    assert bill_state(b, [], today=date(2026, 11, 20)).status == "overdue"
    # due within a week, previous one paid -> due soon
    assert bill_state(b, [date(2026, 11, 10)], today=date(2026, 12, 5)).status == "due_soon"
    # paid early (up to 7 days before) for 10 Dec -> paid, next is 10 Jan
    st = bill_state(b, [date(2026, 11, 10), date(2026, 12, 6)], today=date(2026, 12, 7))
    assert (st.status, st.next_due) == ("paid", date(2027, 1, 10))
    # due dates before the bill was added are never overdue
    fresh = make_bill(first_due=date(2026, 1, 10), created_at=datetime(2026, 11, 15))
    assert bill_state(fresh, [], today=date(2026, 11, 20)).status == "upcoming"
    assert bill_state(make_bill(active=False), [], today=date(2026, 11, 20)).status == "inactive"


def test_payment_counts_for_the_nearest_due_date():
    # first due 28 Nov, added 13 Nov, paid 14 Nov (two weeks early) -> paid, next 28 Dec
    b = make_bill(first_due=date(2026, 11, 28), created_at=datetime(2026, 11, 13))
    st = bill_state(b, [date(2026, 11, 14)], today=date(2026, 11, 14))
    assert (st.status, st.next_due) == ("paid", date(2026, 12, 28))
    # not paid yet -> upcoming, then due soon in the last week
    assert bill_state(b, [], today=date(2026, 11, 14)).status == "upcoming"
    assert bill_state(b, [], today=date(2026, 11, 22)).status == "due_soon"

    monthly = make_bill(first_due=date(2026, 1, 28))
    # a few days late (up to 7) still counts for that due date
    st = bill_state(monthly, [date(2026, 12, 2)], today=date(2026, 12, 3))
    assert (st.status, st.next_due) == ("paid", date(2026, 12, 28))
    # more than 7 days late counts for the next one; the missed one is overdue
    st = bill_state(monthly, [date(2026, 12, 10)], today=date(2026, 12, 11))
    assert (st.status, st.prev_due) == ("overdue", date(2026, 11, 28))
    # the window runs from 7 days after the previous due date: 5 Nov counts for 28 Nov, 4 Nov doesn't
    added_nov = make_bill(first_due=date(2026, 1, 28), created_at=datetime(2026, 11, 1))
    assert bill_state(added_nov, [date(2026, 11, 5)], today=date(2026, 11, 6)).next_due == date(2026, 12, 28)
    assert bill_state(added_nov, [date(2026, 11, 4)], today=date(2026, 11, 6)).next_due == date(2026, 11, 28)
    # a missed due date stays overdue even when the next one is already paid
    st = bill_state(monthly, [date(2026, 11, 20)], today=date(2026, 11, 21))
    assert (st.status, st.prev_due) == ("overdue", date(2026, 10, 28))


# ---------------------------------------------------------------- API


def test_bills_need_login(anon):
    assert anon.get("/api/bills").status_code == 401


def test_bill_crud_and_validation(client):
    body = {"name": " Netflix ", "amount_min": 19_900, "amount_max": 64_900, "first_due": "2026-01-05",
            "match": " netflix, nflx ", "notes": "  "}
    b = client.post("/api/bills", json=body).json()
    assert (b["name"], b["match"], b["notes"], b["repeat"]) == ("Netflix", "netflix, nflx", None, "monthly")
    assert client.post("/api/bills", json=body).status_code == 409
    assert client.post("/api/bills", json={**body, "name": "X", "amount_max": 100}).status_code == 422  # max < min
    assert client.post("/api/bills", json={**body, "name": "Y", "repeat": "daily"}).status_code == 422
    r = client.put(f"/api/bills/{b['id']}", json={**body, "name": "Netflix Premium", "repeat": "yearly"})
    assert r.status_code == 200 and r.json()["name"] == "Netflix Premium" and r.json()["repeat"] == "yearly"
    assert client.get(f"/api/bills/{b['id']}").json()["name"] == "Netflix Premium"
    assert client.delete(f"/api/bills/{b['id']}").status_code == 204
    assert client.get(f"/api/bills/{b['id']}").status_code == 404


def test_new_expense_is_matched_to_a_bill(client, bank):
    bill = client.post("/api/bills", json={"name": "Netflix", "amount_min": 19_900, "amount_max": 64_900,
                                           "first_due": "2026-01-05", "match": "netflix, nflx"}).json()
    hit = spend(client, bank, 64_900, desc="NFLX subscription", payee="Card merchant")
    assert hit["bill"] == {"id": bill["id"], "name": "Netflix"}
    assert spend(client, bank, 99_900, desc="Netflix gift card")["bill"] is None  # amount out of range
    assert spend(client, bank, 19_900, desc="Netflix", auto_match_bill=False)["bill"] is None  # opted out
    by_payee = spend(client, bank, 30_000, desc="Monthly", payee="Netflix India")
    assert by_payee["bill"]["id"] == bill["id"]  # match word in the payee name
    deposit = client.post("/api/transactions", json={"type": "deposit", "date": "2026-11-05", "amount": 19_900,
                                                     "description": "Netflix refund", "source_name": "Netflix",
                                                     "destination_id": bank["id"]}).json()
    assert deposit["bill"] is None  # only expenses link to bills
    listed = client.get("/api/bills").json()[0]
    assert listed["transaction_count"] == 2 and listed["monthly_cost"] == (19_900 + 64_900) // 2
    assert listed["last_paid_amount"] in (64_900, 30_000)


def test_bill_without_words_matches_on_its_name(client, bank):
    client.post("/api/bills", json={"name": "Airtel", "amount_min": 50_000, "amount_max": 80_000, "first_due": "2026-01-01"})
    assert spend(client, bank, 59_900, desc="Airtel postpaid")["bill"]["name"] == "Airtel"


def test_bill_field_filter_and_unlinking(client, bank):
    bill = client.post("/api/bills", json={"name": "Gym", "amount_min": 100, "amount_max": 100_000, "first_due": "2026-01-01"}).json()
    t = spend(client, bank, 500, desc="Membership", bill_id=bill["id"])
    assert t["bill"]["name"] == "Gym"
    assert client.get(f"/api/transactions?bill_id={bill['id']}").json()["total"] == 1
    bad = client.post("/api/transactions", json={"type": "withdrawal", "date": "2026-11-05", "amount": 5, "description": "x",
                                                 "source_id": bank["id"], "destination_name": "S", "bill_id": 9999})
    assert bad.status_code == 422
    # editing never auto-matches: removing the bill keeps it removed
    body = {"type": "withdrawal", "date": "2026-11-05", "amount": 500, "description": "Gym", "source_id": bank["id"],
            "destination_name": "Shop", "bill_id": None}
    assert client.put(f"/api/transactions/{t['id']}", json=body).json()["bill"] is None
    # deleting the bill unlinks its payments, they stay
    t2 = spend(client, bank, 700, bill_id=bill["id"])
    client.delete(f"/api/bills/{bill['id']}")
    assert client.get(f"/api/transactions/{t2['id']}").json()["bill"] is None


def test_overview_upcoming_bills(client):
    due = (TODAY + timedelta(days=3)).isoformat()
    later = (TODAY + timedelta(days=20)).isoformat()
    far = (TODAY + timedelta(days=60)).isoformat()
    client.post("/api/bills", json={"name": "Rent", "amount_min": 2_500_000, "amount_max": 2_500_000, "first_due": due})
    client.post("/api/bills", json={"name": "Insurance", "amount_min": 100_000, "amount_max": 120_000, "first_due": later})
    client.post("/api/bills", json={"name": "Car service", "amount_min": 500_000, "amount_max": 500_000,
                                    "first_due": far, "repeat": "yearly"})
    o = client.get("/api/overview").json()
    assert [(u["name"], u["status"]) for u in o["upcoming_bills"]] == [("Rent", "due_soon"), ("Insurance", "upcoming")]
    assert o["upcoming_bills"][1]["expected"] == 110_000
    # only for the current month
    past = (TODAY.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    assert client.get(f"/api/overview?month={past}").json()["upcoming_bills"] == []

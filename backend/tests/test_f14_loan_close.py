"""A loan paid off early (foreclosed) with one payment, and undoing it. Every number here is made up."""

from app.db import SessionLocal
from app.modules.transactions.models import Transaction

RS = 100
LOAN = {
    "name": "Personal loan", "kind": "personal", "lender": "Example Bank", "principal": 5_00_000 * RS, "rate": 12,
    "tenure": 48, "first_emi_date": "2023-12-05", "start": "existing", "paid_before": 36,
}  # fmt: skip


def _loan(client, bank, **kw):
    r = client.post("/api/loans", json={**LOAN, "pay_from_id": bank["id"], **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _txn(client, tid):
    return client.get(f"/api/transactions/{tid}").json()


def _balance(client, account_id):
    return next(a for a in client.get("/api/accounts").json() if a["id"] == account_id)["balance"]


def test_close_with_a_payment_already_recorded(client, bank):
    """EMIs up to 5 Oct, the rest paid on 19 Oct as a transfer bank -> loan; paid_before
    (36, by date) wrongly counted the 5 Nov EMI too."""
    loan = _loan(client, bank, count_mode="interest_only")
    after_35 = next(r for r in loan["schedule"] if r["n"] == 35)["balance"]
    left = client.get(f"/api/loans/{loan['id']}/payoff?on=2026-10-19").json()["left"]
    assert left == after_35  # what was left after the 5 Oct EMI
    paid = left + 5_309_67
    pay = client.post("/api/transactions", json={
        "type": "transfer", "date": "2026-10-19", "amount": paid, "description": "Payment against loan",
        "source_id": bank["id"], "destination_id": loan["id"],
    }).json()  # fmt: skip
    bank_after_payment = _balance(client, bank["id"])

    r = client.post(
        f"/api/loans/{loan['id']}/close", json={"date": "2026-11-28", "amount": 1, "transaction_id": pay["id"]}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "closed" and out["outstanding"] == 0 and out["closed_on"] == "2026-10-19"
    assert len(out["schedule"]) == 35 and out["next"] is None  # no EMI 36 any more
    (ev,) = out["events"]
    assert ev["mode"] == "close" and ev["amount"] == left
    t = _txn(client, pay["id"])
    assert t["type"] == "transfer" and t["amount"] == paid  # the bank payment stays as it is
    fee = next(
        x for x in client.get(f"/api/transactions?account_id={loan['id']}&limit=50").json()["items"]
        if x["description"].startswith("Closing charges")
    )  # fmt: skip
    assert fee["amount"] == 5_309_67 and fee["category"]["name"] == "Loan Interest"
    assert _balance(client, bank["id"]) == bank_after_payment  # nothing more taken from the bank
    assert client.get("/api/overview?month=2026-11").json()["loans_owed"] == 0

    # closed once only; undo puts everything back
    again = client.post(
        f"/api/loans/{loan['id']}/close", json={"date": "2026-10-19", "amount": paid, "from_account_id": bank["id"]}
    )
    assert again.status_code == 422
    back = client.delete(f"/api/loans/{loan['id']}/events/{ev['id']}").json()
    assert back["status"] == "active" and back["closed_on"] is None and back["paid_before"] == 36
    t = _txn(client, pay["id"])
    assert t["type"] == "transfer" and t["destination"]["id"] == loan["id"]
    with SessionLocal() as db:
        assert db.get(Transaction, pay["id"]).loan_id is None  # no longer the loan's payment
    items = client.get(f"/api/transactions?account_id={loan['id']}&limit=50").json()["items"]
    assert not any(x["description"].startswith("Closing charges") for x in items)


def test_close_with_a_new_payment_whole_emi(client, bank):
    loan = _loan(client, bank)  # whole EMIs count as spending
    left = client.get(f"/api/loans/{loan['id']}/payoff?on=2026-10-19").json()["left"]
    start = _balance(client, bank["id"])
    r = client.post(f"/api/loans/{loan['id']}/close", json={"date": "2026-10-19", "amount": left + 2_000_00})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed" and r.json()["outstanding"] == 0
    assert _balance(client, bank["id"]) == start - left - 2_000_00  # one payment, from "paid from"
    pays = [x for x in client.get(f"/api/transactions?account_id={bank['id']}&limit=50").json()["items"]
            if x["description"].startswith("Loan closed")]  # fmt: skip
    assert len(pays) == 1 and pays[0]["category"]["name"] == "Loan / EMI"


def test_less_than_what_is_left_is_a_part_payment(client, bank):
    loan = _loan(client, bank)
    left = client.get(f"/api/loans/{loan['id']}/payoff?on=2026-10-19").json()["left"]
    r = client.post(f"/api/loans/{loan['id']}/close", json={"date": "2026-10-19", "amount": left - 100})
    assert r.status_code == 422 and "part-payment" in r.json()["detail"]

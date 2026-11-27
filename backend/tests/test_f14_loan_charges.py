"""Loan money received with the lender's charges kept back, and loan accounts as the other side of a
transfer (the loan money into the bank). Every number here is made up."""

RS = 100
LOAN = {
    "name": "Personal loan", "kind": "personal", "lender": "Example Bank", "principal": 5_00_000 * RS, "rate": 12,
    "tenure": 36, "first_emi_date": "2026-12-05", "disbursed_date": "2026-11-05", "start": "new", "money": "received",
}  # fmt: skip


def _txns(client, account_id):
    return client.get(f"/api/transactions?account_id={account_id}&limit=100").json()["items"]


def _balance(client, account_id):
    return next(a for a in client.get("/api/accounts").json() if a["id"] == account_id)["balance"]


def test_charges_kept_by_the_lender(client, bank):
    start = _balance(client, bank["id"])
    r = client.post("/api/loans", json={**LOAN, "received_into_id": bank["id"], "charges": 11_800 * RS})
    assert r.status_code == 201, r.text
    loan = r.json()
    assert loan["principal"] == 5_00_000 * RS  # you still owe the full amount
    rows = {t["description"]: t for t in _txns(client, loan["id"])}
    got, fee = rows["Loan received: Personal loan"], rows["Loan charges: Personal loan"]
    assert got["type"] == "transfer" and got["amount"] == 4_88_200 * RS and got["destination"]["id"] == bank["id"]
    assert (
        fee["type"] == "withdrawal"
        and fee["amount"] == 11_800 * RS
        and fee["category"]["name"] == "Bank Charges & Fees"
    )
    assert _balance(client, bank["id"]) == start + 4_88_200 * RS  # what the bank statement shows

    # deleting the loan takes both entries away
    assert client.delete(f"/api/loans/{loan['id']}").status_code == 204
    assert _balance(client, bank["id"]) == start


def test_charges_must_be_less_than_the_loan(client, bank):
    r = client.post("/api/loans", json={**LOAN, "received_into_id": bank["id"], "charges": 5_00_000 * RS})
    assert r.status_code == 422


def test_no_charges_is_as_before(client, bank):
    loan = client.post("/api/loans", json={**LOAN, "received_into_id": bank["id"]}).json()
    (t,) = _txns(client, loan["id"])
    assert t["amount"] == 5_00_000 * RS and t["description"] == "Loan received: Personal loan"


def test_bank_credit_becomes_a_transfer_from_the_loan(client, bank):
    """A loan added with "Don't record it": the bank's credit is turned into loan -> bank, and the
    fee is an expense paid from the loan."""
    loan = client.post("/api/loans", json={**LOAN, "money": "none"}).json()
    credit = client.post("/api/transactions", json={
        "type": "deposit", "date": "2026-11-05", "amount": 4_88_200 * RS, "description": "NEFT EXAMPLE BANK LOAN",
        "destination_id": bank["id"], "source_name": "Example Bank",
    }).json()  # fmt: skip
    r = client.put(f"/api/transactions/{credit['id']}", json={
        "type": "transfer", "date": "2026-11-05", "amount": 4_88_200 * RS, "description": "NEFT EXAMPLE BANK LOAN",
        "source_id": loan["id"], "destination_id": bank["id"],
    })  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["source"]["id"] == loan["id"] and r.json()["type"] == "transfer"
    fee = client.post("/api/transactions", json={
        "type": "withdrawal", "date": "2026-11-05", "amount": 11_800 * RS, "description": "Processing fee",
        "source_id": loan["id"], "destination_name": "Example Bank",
    })  # fmt: skip
    assert fee.status_code == 201, fee.text
    ov = client.get("/api/overview?month=2026-11").json()
    assert ov["income"] == 0  # loan money isn't income

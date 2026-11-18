"""F15 Investments step 3 — linking payments: "Move past payments here" and bank statement
rows suggested as transfers to an investment. Names, numbers and amounts are made up."""

from types import SimpleNamespace

from app.modules.investments.matching import best, score

from .test_statement_import import PASSWORD, add_email


def _inv(account_id=1, **kw):
    base = dict(
        account_id=account_id, kind="fd", subtype=None, institution=None, person=None, number=None, instalment=None,
        closed_on=None, fund=None, account=SimpleNamespace(name=kw.pop("name", "Investment")),
    )  # fmt: skip
    return SimpleNamespace(**{**base, **kw})


def test_matching_rules():
    fund = SimpleNamespace(
        scheme="Examplar Flexi Cap Fund - Direct Growth", amc="Examplar Mutual Fund", folio="9988776/12"
    )
    mf = _inv(1, kind="mf", fund=fund, instalment=500_000, name="Examplar Flexi Cap Fund")
    assert score(mf, "ACH D- BSE LTD SIP 0001", 500_000)  # kind word + the SIP amount
    assert score(mf, "NACH EXAMPLAR MF", 123_400)  # the fund's name + a kind word
    assert score(mf, "UPI/SWIGGY/food", 500_000) is None  # the amount alone isn't enough
    assert score(mf, "SIP folio 9988776", 1) and score(mf, "SIP folio 9988776", 1).why.startswith("number")

    lic = _inv(2, kind="insurance", subtype="endowment", institution="LIC of India", instalment=2_500_000)
    assert score(lic, "LIC PREMIUM ONLINE", 2_500_000)
    term = _inv(3, kind="insurance", subtype="term", institution="LIC", instalment=2_500_000)
    assert score(term, "LIC PREMIUM ONLINE", 2_500_000) is None  # term premiums are spending

    fd = _inv(4, kind="fd", institution="HDFC Bank", number="50300012345678")
    assert score(fd, "HDFC CREDIT CARD PAYMENT", 1_200_000) is None  # a bank's name alone
    assert score(fd, "FD BOOKED HDFC", 10_000_000)
    assert score(fd, "TRF TO FD 5678", 10_000_000)
    assert score(fd, "NEFT CR SALARY", -9_000_000) is None  # money in needs a "maturity"-type word
    assert score(fd, "FD MATURITY PROCEEDS 5678", -10_700_000)

    lent = _inv(5, kind="lent", person="Suresh Patel", name="Lent to Suresh Patel")
    assert score(lent, "UPI/SURESH PATEL/repay", -1_000_000)
    assert score(lent, "UPI/MAHESH/rent", 1_000_000) is None

    # two SIPs of the same amount with no name: no guess
    other = _inv(
        6, kind="mf", fund=SimpleNamespace(scheme="Other Index Fund", amc=None, folio=None), instalment=500_000
    )
    assert best([mf, other], "ACH D- BSE LTD SIP", 500_000) is None
    assert best([mf, other], "ACH EXAMPLAR SIP", 500_000).account_id == 1


def _fund(client, **extra):
    r = client.post("/api/investments", json={
        "kind": "mf", "quantity": 100, "instalment": 500_000,
        "fund": {"scheme": "Examplar Flexi Cap Fund - Direct Growth", "isin": "INF000Z01019", "nav": 1_000_000},
        **extra,
    })  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


def _spend(client, bank, amount, desc, date="2026-10-05", payee="BSE Ltd"):
    r = client.post("/api/transactions", json={
        "type": "withdrawal", "date": date, "amount": amount, "description": desc,
        "source_id": bank["id"], "destination_name": payee,
    })  # fmt: skip
    return r.json()


def test_move_past_payments(client, bank):
    inv = _fund(client, amount=1_000_000)  # ₹10,000 "already invested"
    sip1 = _spend(client, bank, 500_000, "ACH D- BSE LTD SIP", "2026-09-05")
    sip2 = _spend(client, bank, 500_000, "ACH D- BSE LTD SIP", "2026-10-05")
    same = _spend(client, bank, 500_000, "UPI/SHOP/xyz", "2026-10-07", payee="Shop")  # same amount, no words
    _spend(client, bank, 45_000, "UPI/SWIGGY/food", "2026-10-06", payee="Swiggy")
    rows = {r["transaction_id"]: r for r in client.get(f"/api/investments/{inv['id']}/linkable").json()}
    assert rows[sip1["id"]]["suggested"] and rows[sip2["id"]]["suggested"]
    assert not rows[same["id"]]["suggested"]  # shown (same amount) but not ticked
    assert len(rows) == 3

    r = client.post(f"/api/investments/{inv['id']}/link", json={"ids": [sip1["id"], sip2["id"]], "lower_opening": True})
    assert r.status_code == 200, r.text
    out = r.json()["investment"]
    assert out["opening"] == 0 and out["invested"] == 1_000_000  # the payments replace the opening amount
    assert len(out["moves"]) == 2
    assert client.get("/api/overview?month=2026-10").json()["spending"] == 500_000 + 45_000  # SIP no longer spending
    assert sip2["id"] not in {x["transaction_id"] for x in client.get(f"/api/investments/{inv['id']}/linkable").json()}
    # a linked transfer can't be linked again
    assert client.post(f"/api/investments/{inv['id']}/link", json={"ids": [sip1["id"]]}).status_code == 422


def test_bank_statement_suggests_the_investment(client):
    bank = client.post("/api/accounts", json={"name": "ICICI Savings", "type": "asset", "account_number": "XXXX2840",
                                              "opening_balance": 5_000_000}).json()  # fmt: skip
    inv = _fund(client)
    lines = [
        "ICICI BANK STATEMENT",
        "Savings A/c XXXXXXXX2840",
        "DATE MODE PARTICULARS DEPOSITS WITHDRAWALS BALANCE",
        "01-11-2026 B/F 50,000.00",
        "02-11-2026 UPI/SWIGGY/swiggy@ybl/food/ICICI 450.00 49,550.00",
        "05-11-2026 ACH/BSE LTD SIP/EXAMPLAR 5,000.00 44,550.00",
        "30-11-2026 CLOSING BALANCE 44,550.00",
    ]  # fmt: skip
    att = add_email(lines, mid="sip-stmt")
    d = client.post("/api/statements", json={"attachment_id": att, "password": PASSWORD}).json()
    sip = next(r for r in d["rows"] if "SIP" in r["description"].upper())
    assert sip["kind"] == "transfer" and sip["transfer_account_id"] == inv["id"]
    assert sip["suggestion_kind"] == "investment"
    other = next(r for r in d["rows"] if "SWIGGY" in r["description"].upper())
    assert other["kind"] == "expense"
    client.patch(f"/api/statements/{d['id']}/rows/{other['id']}", json={"include": False})
    r = client.post(f"/api/statements/{d['id']}/import")
    assert r.status_code == 200, r.text
    moves = client.get(f"/api/investments/{inv['id']}").json()["moves"]
    assert [(m["type"], m["amount"], m["source"]["id"]) for m in moves] == [("transfer", 500_000, bank["id"])]

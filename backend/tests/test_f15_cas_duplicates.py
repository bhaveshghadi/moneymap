"""CAS import: the same fund, the same CAS rows and the same bank payment are never recorded twice.
Every name, folio and ISIN is made up."""

from .test_f15_mutual_funds import CAS_LINES, ISIN
from .test_statement_import import PASSWORD, add_email


def _open(client, mid) -> dict:
    att = add_email(CAS_LINES, mid=mid, sender="CAMS <donotreply@camsonline.com>", password=None)
    detail = client.post("/api/statements", json={"attachment_id": att}).json()["detail"]
    return client.get(f"/api/investments/cas/{detail['cas_id']}").json()


def _hand_fund(client, **fund):
    r = client.post("/api/investments", json={
        "kind": "mf", "quantity": 50, "amount": 1_000_000,  # ₹10,000 already invested
        "fund": {"scheme": "Example Flexi Cap Fund - Direct Growth", "nav": 1_000_000, **fund},
    })  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


def test_joins_a_fund_added_by_hand_without_counting_twice(client, bank):
    inv = _hand_fund(client, isin=ISIN)
    cas = _open(client, "dup-a")
    (f,) = cas["funds"]
    assert f["account_id"] == inv["id"]  # same ISIN: joins it, no second fund
    assert f["replaces_opening"] == 1_000_000 and f["units_now"] == 50
    out = client.post(f"/api/investments/cas/{cas['id']}/import").json()
    assert out["accounts_created"] == 0 and out["opening_replaced"] == 1
    (one,) = client.get("/api/investments").json()
    # no bank history: both CAS rows are older purchases (₹15,000), replacing the hand-entered ₹10,000
    assert one["opening"] == 1_500_000 and one["invested"] == 1_500_000 and one["fund"]["units"] == 140  # not 25,000


def test_same_name_without_isin_is_the_same_fund(client):
    inv = _hand_fund(client)  # typed by hand: no ISIN
    cas = _open(client, "dup-b")
    assert cas["funds"][0]["account_id"] == inv["id"]


def test_a_fund_goes_to_one_place_only(client):
    inv = _hand_fund(client, isin=ISIN)
    lines = CAS_LINES[:-1] + [
        CAS_LINES[-1],
        "Example Mutual Fund",
        "Folio No: 5555555/55 PAN: XXXXX0000X",
        "ABC9-Example Liquid Fund - Direct Growth - ISIN: INF000X01099(Advisor: DIRECT) Registrar : CAMS",
        "Opening Unit Balance: 0.000",
        "05-Feb-2026 Purchase 1,000.00 1.000 1000.0000 1.000",
        "Closing Unit Balance: 1.000 NAV on 31-Oct-2026: INR 1010.0000 Total Cost Value: 1,000.00",
    ]
    att = add_email(lines, mid="dup-c", sender="CAMS <donotreply@camsonline.com>", password=None)
    cid = client.post("/api/statements", json={"attachment_id": att}).json()["detail"]["cas_id"]
    cas = client.get(f"/api/investments/cas/{cid}").json()
    second = next(f for f in cas["funds"] if f["isin"] != ISIN)
    r = client.patch(f"/api/investments/cas/{cid}/funds/{second['id']}", json={"account_id": inv["id"]})
    assert r.status_code == 422


def test_rows_and_bank_payments_are_not_repeated(client, bank):
    client.post("/api/transactions", json={
        "type": "withdrawal", "date": "2026-01-01", "amount": 100, "description": "Tea",
        "source_id": bank["id"], "destination_name": "Shop",
    })  # fmt: skip
    first = _open(client, "dup-d")
    client.post(f"/api/investments/cas/{first['id']}/import")  # both rows -> new transfers with the bank
    inv = client.get("/api/investments").json()[0]
    assert len(client.get(f"/api/investments/{inv['id']}").json()["moves"]) == 2

    # the same CAS again from another email: every row is already in — nothing new
    again = _open(client, "dup-e")
    assert again["id"] != first["id"] and all(r["existing"] for r in again["rows"])
    assert again["funds"][0]["already_imported"] == 2
    out = client.post(f"/api/investments/cas/{again['id']}/import").json()
    assert out.get("created", 0) == 0 and out.get("linked", 0) == 0
    assert len(client.get(f"/api/investments/{inv['id']}").json()["moves"]) == 2

    # the bank statement arrives later: its SIP debit (4 days before the fund's date) is the same payment
    acct = client.post("/api/accounts", json={"name": "ICICI Savings", "type": "asset", "account_number": "XXXX2840",
                                              "opening_balance": 5_000_000}).json()  # fmt: skip
    # (the CAS transfers came from the first bank; move the SIP to this one to match the statement)
    sip = next(m for m in client.get(f"/api/investments/{inv['id']}").json()["moves"] if m["date"] == "2026-10-05")
    full = client.get(f"/api/transactions/{sip['id']}").json()
    client.put(f"/api/transactions/{sip['id']}", json={
        "type": "transfer", "date": full["date"], "amount": full["amount"], "description": full["description"],
        "source_id": acct["id"], "destination_id": inv["id"],
    })  # fmt: skip
    lines = [
        "ICICI BANK STATEMENT",
        "Savings A/c XXXXXXXX2840",
        "DATE MODE PARTICULARS DEPOSITS WITHDRAWALS BALANCE",
        "01-10-2026 B/F 50,000.00",
        "01-10-2026 ACH/BSE LTD SIP/EXAMPLE 5,000.00 45,000.00",
        "31-10-2026 CLOSING BALANCE 45,000.00",
    ]
    att = add_email(lines, mid="dup-stmt")
    d = client.post("/api/statements", json={"attachment_id": att, "password": PASSWORD}).json()
    row = next(r for r in d["rows"] if "SIP" in r["description"].upper())
    assert row["duplicate_of"] == sip["id"] and row["include"] is False


def test_untick_and_tick_a_fund(client):
    inv = _hand_fund(client, isin=ISIN)
    cas = _open(client, "dup-f")
    fid = cas["funds"][0]["id"]
    off = client.patch(f"/api/investments/cas/{cas['id']}/funds/{fid}", json={"skip": True}).json()
    assert off["funds"][0]["skip"] and all(r["action"] == "skip" for r in off["rows"])
    on = client.patch(f"/api/investments/cas/{cas['id']}/funds/{fid}", json={"auto": True}).json()
    assert not on["funds"][0]["skip"] and on["funds"][0]["account_id"] == inv["id"]  # suggested again

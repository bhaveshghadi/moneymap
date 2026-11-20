"""CAS review: per fund, import both / the fund only (today's holding) / the transactions only.
Every name, folio and ISIN here is made up."""

from .test_f15_mutual_funds import CAS_LINES, ISIN, _cas
from .test_statement_import import add_email


def _mode(client, cas, mode):
    fid = cas["funds"][0]["id"]
    return client.patch(f"/api/investments/cas/{cas['id']}/funds/{fid}/mode", json={"mode": mode})


def _sip(client, bank):
    return client.post("/api/transactions", json={
        "type": "withdrawal", "date": "2026-10-04", "amount": 500_000, "description": "ACH SIP EXAMPLE MF",
        "source_id": bank["id"], "destination_name": "Example MF",
    }).json()  # fmt: skip


def test_fund_only_then_both_later(client, bank):
    sip = _sip(client, bank)
    cas = _cas(client)
    r = _mode(client, cas, "fund")
    assert r.status_code == 200 and r.json()["funds"][0]["mode"] == "fund"
    out = client.post(f"/api/investments/cas/{cas['id']}/import").json()
    assert (out["funds_only"], out["accounts_created"]) == (1, 1)
    assert out.get("converted", 0) == out.get("before", 0) == 0

    (inv,) = client.get("/api/investments").json()
    assert inv["fund"]["units"] == 140 and inv["fund"]["nav"] == 130 and inv["value"] == 18_200_00
    assert inv["invested"] == 15_000_00  # the CAS cost counts as already invested
    assert client.get(f"/api/investments/{inv['id']}").json()["fund_txns"] == []
    t = next(x for x in client.get("/api/transactions").json()["items"] if x["id"] == sip["id"])
    assert t["type"] == "withdrawal"  # the bank SIP is left alone

    # a later CAS imported with both: the rows replace the stand-in "already invested" (no double count)
    att = add_email(CAS_LINES, mid="cas-mf-later", sender="CAMS <donotreply@camsonline.com>", password=None)
    cid = client.post("/api/statements", json={"attachment_id": att}).json()["detail"]["cas_id"]
    later = client.get(f"/api/investments/cas/{cid}").json()
    assert later["funds"][0]["account_id"] == inv["id"] and later["funds"][0]["mode"] == "both"
    assert not any(r["existing"] for r in later["rows"])
    out = client.post(f"/api/investments/cas/{cid}/import").json()
    assert out["converted"] == 1 and out["before"] == 1 and out["opening_replaced"] == 1
    inv = client.get(f"/api/investments/{inv['id']}").json()
    assert inv["invested"] == 1_000_000 + 500_000
    assert len(inv["fund_txns"]) == 2


def test_transactions_only_into_a_fund_you_have(client, bank):
    hand = client.post("/api/investments", json={
        "kind": "mf", "quantity": 10.5, "amount": 1_000_00,
        "fund": {"scheme": "My Flexi Cap", "isin": ISIN, "nav": 1_000_000, "nav_date": "2026-11-01"},
    }).json()  # fmt: skip
    cas = _cas(client)
    assert cas["funds"][0]["account_id"] == hand["id"]  # joined by ISIN
    r = _mode(client, cas, "txns")
    assert r.status_code == 200, r.text
    out = client.post(f"/api/investments/cas/{cas['id']}/import").json()
    assert out["before"] + out.get("transfer", 0) + out.get("created", 0) >= 1
    inv = client.get(f"/api/investments/{hand['id']}").json()
    # name, units and price untouched; the CAS rows are in
    assert inv["name"] == hand["name"] and inv["fund"]["scheme"] == "My Flexi Cap"
    assert inv["fund"]["units"] == 10.5 and inv["fund"]["nav"] == 100
    assert len(inv["fund_txns"]) == 2
    assert inv["invested"] == 1_000_000 + 500_000  # the CAS rows, not also the hand-entered ₹1,000


def test_transactions_only_needs_a_fund(client, bank):
    cas = _cas(client)  # no fund yet: goes to a new one
    r = _mode(client, cas, "txns")
    assert r.status_code == 422 and "already have" in r.json()["detail"]["message"]
    # leaving a fund out and picking a mode brings it back
    fid = cas["funds"][0]["id"]
    client.patch(f"/api/investments/cas/{cas['id']}/funds/{fid}", json={"skip": True})
    r = _mode(client, cas, "fund").json()
    assert r["funds"][0]["skip"] is False and r["funds"][0]["mode"] == "fund"


def test_deleted_fund_reopens_the_cas(client, bank):
    """Delete the fund a CAS made, open the same CAS again: it can be imported again."""
    att = add_email(CAS_LINES, mid="cas-mf-again", sender="CAMS <donotreply@camsonline.com>", password=None)
    first = client.post("/api/statements", json={"attachment_id": att}).json()["detail"]["cas_id"]
    assert client.post(f"/api/investments/cas/{first}/import").status_code == 200
    (inv,) = client.get("/api/investments").json()
    assert client.delete(f"/api/investments/{inv['id']}").status_code == 204

    # the same PDF opened again: the earlier CAS, back to a draft
    cid = client.post("/api/statements", json={"attachment_id": att}).json()["detail"]["cas_id"]
    assert cid == first
    again = client.get(f"/api/investments/cas/{cid}").json()
    assert again["status"] == "draft" and again["imported_at"] is None
    assert not any(r["existing"] for r in again["rows"]) and again["funds"][0]["account_id"] is None
    out = client.post(f"/api/investments/cas/{cid}/import").json()
    assert out["accounts_created"] == 1
    (inv,) = client.get("/api/investments").json()
    assert inv["fund"]["units"] == 140 and len(client.get(f"/api/investments/{inv['id']}").json()["fund_txns"]) == 2

    # nothing deleted: opening it again keeps it imported
    assert client.get(f"/api/investments/cas/{cid}").json()["status"] == "imported"

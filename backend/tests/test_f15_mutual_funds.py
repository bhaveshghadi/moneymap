"""F15 Investments step 2 — mutual funds: CAS reader, review + import, AMFI prices, fund by hand.
Every name, folio and ISIN here is made up."""

from datetime import date

from app.db import SessionLocal
from app.modules.investments.cas import parse_cas
from app.modules.investments.nav import parse_navall, search_schemes, update_navs

from .test_statement_import import add_email

ISIN = "INF000X01011"
CAS_LINES = [
    "Consolidated Account Statement",
    "01-Jan-2026 To 31-Oct-2026",
    "Example Mutual Fund",
    "Folio No: 1234567/89 PAN: XXXXX0000X",
    f"ABC1-Example Flexi Cap Fund - Direct Growth - ISIN: {ISIN}(Advisor: DIRECT) Registrar : CAMS",
    "Opening Unit Balance: 0.000",
    "05-Jan-2026 Purchase 9,999.50 100.000 99.9950 100.000",
    "05-Jan-2026 *** Stamp Duty *** 0.50",
    "05-Oct-2026 Systematic Investment (1) 4,999.75 40.000 124.9938 140.000",
    "05-Oct-2026 *** Stamp Duty *** 0.25",
    "Closing Unit Balance: 140.000 NAV on 31-Oct-2026: INR 130.0000 Total Cost Value: 15,000.00",
    "Market Value on 31-Oct-2026: INR 18,200.00",
]
NAVALL = f"""Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

Example Mutual Fund

123456;{ISIN};-;Example Flexi Cap Fund - Direct Growth;135.5000;18-Nov-2026
123457;INF000X01029;-;Example Flexi Cap Fund - Regular Growth;120.0000;18-Nov-2026
"""


def test_parse_cas():
    st = parse_cas("\n".join(CAS_LINES))
    assert st.period_from == date(2026, 1, 1) and st.period_to == date(2026, 10, 31)
    (f,) = st.funds
    assert f.isin == ISIN and f.folio == "1234567/89" and f.amc == "Example Mutual Fund"
    assert f.closing_units == 140_000 and f.nav == 1_300_000 and f.cost == 1_500_000
    assert [t.kind for t in f.txns] == ["purchase", "sip"]
    assert f.txns[0].stamp_duty == 50 and f.txns[1].amount == 499_975


def test_parse_navall_and_search():
    navs = parse_navall(NAVALL)
    assert navs[ISIN] == ("123456", 1_355_000, date(2026, 11, 18))
    hits = search_schemes("flexi example", text=NAVALL)
    assert hits[0]["isin"] == ISIN and hits[0]["amc"] == "Example Mutual Fund"  # Direct first


def _cas(client) -> dict:
    att = add_email(CAS_LINES, mid="cas-mf", sender="CAMS <donotreply@camsonline.com>", password=None)
    detail = client.post("/api/statements", json={"attachment_id": att}).json()["detail"]
    assert detail["code"] == "cas"
    return client.get(f"/api/investments/cas/{detail['cas_id']}").json()


def test_cas_review_and_import(client, bank):
    # the October SIP is already in the bank statement as an expense
    sip = client.post("/api/transactions", json={
        "type": "withdrawal", "date": "2026-10-04", "amount": 500_000, "description": "ACH SIP EXAMPLE MF",
        "source_id": bank["id"], "destination_name": "Example MF",
    }).json()  # fmt: skip
    cas = _cas(client)
    assert cas["status"] == "draft" and len(cas["funds"]) == 1
    rows = {r["date"]: r for r in cas["rows"]}
    assert rows["2026-01-05"]["action"] == "before"  # older than your records
    assert rows["2026-10-05"]["action"] == "convert" and rows["2026-10-05"]["match"]["id"] == sip["id"]

    r = client.post(f"/api/investments/cas/{cas['id']}/import")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["accounts_created"] == 1 and out["converted"] == 1 and out["before"] == 1

    (inv,) = client.get("/api/investments").json()
    assert inv["kind"] == "mf" and inv["name"].startswith("Example Flexi Cap Fund")
    assert inv["fund"]["units"] == 140 and inv["fund"]["nav"] == 130
    assert inv["value"] == 18_200_00 and inv["invested"] == 1_000_000 + 500_000
    ov = client.get("/api/overview?month=2026-10").json()
    assert ov["spending"] == 0  # the SIP is a transfer now, not spending
    detail = client.get(f"/api/investments/{inv['id']}").json()
    assert [t["kind"] for t in detail["fund_txns"]] == ["sip", "purchase"]

    # the same CAS again (another email): every row is already in
    att2 = add_email(CAS_LINES, mid="cas-mf-2", sender="CAMS <donotreply@camsonline.com>", password=None)
    d2 = client.post("/api/statements", json={"attachment_id": att2}).json()["detail"]
    if d2["cas_id"] != cas["id"]:
        again = client.get(f"/api/investments/cas/{d2['cas_id']}").json()
        assert all(r["existing"] for r in again["rows"])
        assert again["funds"][0]["account_id"] == inv["id"]


def test_cas_row_choices(client, bank):
    client.post(
        "/api/transactions",
        json={
            "type": "withdrawal",
            "date": "2026-01-01",
            "amount": 100,
            "description": "Tea",
            "source_id": bank["id"],
            "destination_name": "Shop",
        },
    )  # fmt: skip  (records start 1 Jan: no row is "before")
    cas = _cas(client)
    rows = sorted(cas["rows"], key=lambda r: r["date"])
    assert {r["action"] for r in rows} == {"transfer"}
    first = rows[0]
    r = client.patch(f"/api/investments/cas/{cas['id']}/rows/{first['id']}", json={"action": "before"})
    assert r.status_code == 200 and next(x for x in r.json()["rows"] if x["id"] == first["id"])["user_set"]
    out = client.post(f"/api/investments/cas/{cas['id']}/import").json()
    assert out["created"] == 1 and out["before"] == 1
    bal = client.get(f"/api/accounts/{bank['id']}").json()["balance"]
    assert bal == 10_000_000 - 100 - 500_000  # SIP with its stamp duty, as a transfer
    assert client.post(f"/api/investments/cas/{cas['id']}/import").status_code == 409


def test_skip_fund_and_discard(client, bank):
    cas = _cas(client)
    fid = cas["funds"][0]["id"]
    r = client.patch(f"/api/investments/cas/{cas['id']}/funds/{fid}", json={"skip": True})
    assert all(x["action"] == "skip" for x in r.json()["rows"])
    assert client.delete(f"/api/investments/cas/{cas['id']}").status_code == 204
    assert client.get("/api/investments/cas").json() == []


def test_fund_by_hand_and_nav_update(client, bank):
    r = client.post("/api/investments", json={
        "kind": "mf", "quantity": 10.5, "amount": 1_000_00,
        "fund": {"scheme": "Example Flexi Cap Fund - Direct Growth", "isin": ISIN, "nav": 1_000_000,
                 "nav_date": "2026-11-01"},
    })  # fmt: skip
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["fund"]["units"] == 10.5 and inv["value"] == 1_050_00  # 10.5 x ₹100
    with SessionLocal() as db:
        status = update_navs(db, NAVALL)
    assert status["updated"] == 1
    inv = client.get(f"/api/investments/{inv['id']}").json()
    assert inv["fund"]["nav"] == 135.5 and inv["fund"]["nav_source"] == "amfi"
    assert inv["value"] == round(10_500 * 1_355_000 / 100_000)
    r = client.patch(f"/api/investments/{inv['id']}", json={"quantity": 20})
    assert r.json()["fund"]["units"] == 20
    assert client.post("/api/investments", json={"kind": "mf", "quantity": 1}).status_code == 422
    assert client.get("/api/investments/nav/status").json()["updated"] == 1

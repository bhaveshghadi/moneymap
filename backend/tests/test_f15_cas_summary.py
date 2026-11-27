"""A summary CAS ("Consolidated Account Summary": holdings only, no transactions) imports each fund
as "fund only"; a detailed CAS later joins the same funds. Every name, folio and ISIN here is made up."""

from datetime import date

from app.modules.investments.cas import is_cas, is_summary, parse_cas
from app.modules.statements.router import is_cas as statement_is_cas

from .test_f15_mutual_funds import CAS_LINES, ISIN
from .test_statement_import import add_email

SUMMARY_LINES = [
    "Consolidated Account Summary",
    "As on 01-Nov-2026",
    "Folio No. ISIN Scheme Name Cost Value Unit Balance NAV Date NAV Market Value Registrar",
    "(INR) (INR) (INR)",
    f"1234567/89 {ISIN} ABC1 - Example Flexi Cap Fund - Direct   15,000.000   140.000 31-Oct-2026   130.00   18,200.00   CAMS",
    "Growth (Non-Demat)",
    "98765432101/0INF000Y01022 XYZLIQ - EXAMPLE LIQUID FUND -   20,000.000   5.000 01-Nov-2026   4,100.5000   20,502.50 KFINTECH",
    "DIRECT PLAN GROWTH PLAN - GROWTH",
    "OPTION (Non Demat)",
    "Total   35,000.00   38,702.50",
]


def test_reads_a_summary():
    text = "\n".join(SUMMARY_LINES)
    assert is_cas(text) and is_summary(text) and statement_is_cas(text)
    assert not is_summary("\n".join(CAS_LINES))  # the detailed one reads as before
    st = parse_cas(text)
    assert st.summary and st.period_from is None and st.period_to == date(2026, 11, 1)
    a, b = st.funds
    assert (a.folio, a.isin, a.scheme, a.registrar) == (
        "1234567/89",
        ISIN,
        "Example Flexi Cap Fund - Direct Growth",
        "CAMS",
    )
    assert (a.cost, a.closing_units, a.nav, a.nav_date, a.market_value) == (
        15_000_00, 140_000, 130_0000, date(2026, 10, 31), 18_200_00,
    )  # fmt: skip
    assert (b.folio, b.isin, b.registrar) == ("98765432101/0", "INF000Y01022", "KFINTECH")
    assert b.scheme == "EXAMPLE LIQUID FUND - DIRECT PLAN GROWTH PLAN - GROWTH OPTION"
    assert (b.closing_units, b.nav, b.market_value) == (5_000, 4100_5000, 20_502_50)
    assert not a.txns and not b.txns


def _open(client, lines, mid):
    att = add_email(lines, mid=mid, sender="CAMS <donotreply@camsonline.com>", password=None)
    detail = client.post("/api/statements", json={"attachment_id": att}).json()["detail"]
    assert detail["code"] == "cas", detail
    return client.get(f"/api/investments/cas/{detail['cas_id']}").json()


def test_summary_imports_holdings_then_detailed_joins(client, bank):
    cas = _open(client, SUMMARY_LINES, "cas-summary")
    assert cas["summary"] and cas["period_to"] == "2026-11-01" and not cas["rows"]
    assert [f["mode"] for f in cas["funds"]] == ["fund", "fund"]
    fid = cas["funds"][0]["id"]
    r = client.patch(f"/api/investments/cas/{cas['id']}/funds/{fid}/mode", json={"mode": "both"})
    assert r.status_code == 422  # no transactions to bring in

    r = client.post(f"/api/investments/cas/{cas['id']}/import")
    assert r.status_code == 200, r.text
    assert r.json()["accounts_created"] == 2 and r.json()["funds_only"] == 2
    invs = {i["fund"]["isin"]: i for i in client.get("/api/investments").json()}
    flexi = invs[ISIN]
    assert flexi["fund"]["units"] == 140 and flexi["invested"] == 15_000_00 and flexi["value"] == 18_200_00
    assert invs["INF000Y01022"]["invested"] == 20_000_00

    # the detailed CAS later: same fund (by ISIN), its rows replace the "already invested" amount
    det = _open(client, CAS_LINES, "cas-detailed")
    assert not det["summary"] and det["funds"][0]["account_id"] == flexi["id"]
    assert client.post(f"/api/investments/cas/{det['id']}/import").status_code == 200
    after = {i["fund"]["isin"]: i for i in client.get("/api/investments").json()}
    assert len(after) == 2 and after[ISIN]["invested"] == 15_000_00  # 9,999.50 + 0.50 + 4,999.75 + 0.25, once
    detail = client.get(f"/api/investments/{flexi['id']}").json()
    assert [t["kind"] for t in detail["fund_txns"]] == ["sip", "purchase"]

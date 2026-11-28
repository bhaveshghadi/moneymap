"""Bonds: payout schedule (interest-only and amortising), value, recording / splitting / undoing payouts.
Made-up bonds and numbers."""

from datetime import date, timedelta
from types import SimpleNamespace

from app.core.dates import add_months
from app.modules.investments.values import Rates, bond_schedule, value_of

from .helpers import balance

TODAY = date.today()


def _bond(**kw):
    base = dict(
        kind="bond", subtype="ncd", rate_bp=1000, compounding=None, start_date=date(2026, 1, 10),
        maturity_date=date(2027, 1, 15), months=None, instalment=None, frequency="monthly", sum_assured=None,
        maturity_amount=None, quantity=10_000, purity=None, unit_price=None, current_value=None, value_date=None,
        payout_on=None, payout_amount=None, face_value=1_000_00, repayment="bullet",
    )  # fmt: skip
    return SimpleNamespace(**{**base, **kw})


# ---------------------------------------------------------------- schedule and value (pure)


def test_bullet_schedule_interest_each_month_principal_at_maturity():
    rows = bond_schedule(_bond())  # 10 units x ₹1,000 at 10%, monthly, dates on the 15th
    assert rows[0].date == date(2026, 1, 15) and rows[-1].date == date(2027, 1, 15)
    assert len(rows) == 13
    assert rows[0].interest == round(10_000_00 * 0.10 * 5 / 365)  # short first period: 5 days
    assert rows[1].interest == round(10_000_00 * 0.10 * 31 / 365)  # 15 Jan -> 15 Feb
    assert all(r.principal == 0 for r in rows[:-1]) and rows[-1].principal == 10_000_00
    assert rows[-1].outstanding == 0


def test_amortising_schedule_pays_back_all_principal():
    rows = bond_schedule(_bond(repayment="amortising", start_date=date(2026, 1, 15), maturity_date=date(2027, 1, 15)))
    assert len(rows) == 12
    assert sum(r.principal for r in rows) == 10_000_00 and rows[-1].outstanding == 0
    totals = [r.interest + r.principal for r in rows]
    assert max(totals[:-1]) - min(totals[:-1]) <= 1  # an equal amount each month
    assert rows[0].interest == round(10_000_00 * 0.10 / 12)
    assert rows[0].principal < rows[-1].principal  # more principal as interest falls


def test_single_payout_at_maturity():
    rows = bond_schedule(_bond(frequency="single", start_date=date(2026, 1, 1), maturity_date=date(2027, 1, 1)))
    assert len(rows) == 1 and rows[0].principal == 10_000_00 and rows[0].interest == 1_000_00


def test_value_is_principal_still_to_come_back():
    b = _bond(repayment="amortising")
    v = value_of(b, [(date(2026, 1, 10), 10_050_00), (date(2026, 2, 15), -800_00)], date(2026, 3, 1), Rates())
    assert v.value == 10_000_00 - 800_00  # face less principal back (bought at a premium: gain < 0)
    assert v.invested == 9_250_00 and v.gain == -50_00
    whats = {d.what for d in v.dues}
    assert whats == {"matures", "payout"}


# ---------------------------------------------------------------- API


def _add(client, **body):
    r = client.post("/api/investments", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _new_bond(client, bank, repayment="amortising"):
    start = TODAY - timedelta(days=70)
    return _add(client, kind="bond", subtype="ncd", institution="Acme Finance", platform="Wint", rating="A (TEST)",
                number="INE000A00000", quantity=10, face_value=1_000_00, amount=10_000_00, rate=10.5,
                frequency="monthly", repayment=repayment, start_date=str(start),
                maturity_date=str(add_months(start, 24)), money="bank", pay_from_id=bank["id"])  # fmt: skip


def test_add_bond_checks_and_detail(client, bank):
    r = client.post("/api/investments", json={"kind": "bond", "subtype": "ncd", "amount": 100})
    assert r.status_code == 422
    b = _new_bond(client, bank)
    assert b["name"] == "Acme Finance Bond" and b["platform"] == "Wint" and b["repayment"] == "amortising"
    assert balance(client, bank["id"]) == 10_000_000 - 10_000_00
    assert b["value"] == 10_000_00 and b["bond"]["face"] == 10_000_00
    sched = b["bond"]["schedule"]
    assert len(sched) == 24 and sched[-1]["outstanding"] == 0
    assert [r["status"] for r in sched[:2]] == ["missed", "missed"]  # ~70 days in, nothing recorded yet
    assert b["next_due"]["what"] == "payout"


def test_record_payout_splits_interest_and_principal(client, bank):
    b = _new_bond(client, bank)
    row = b["bond"]["schedule"][0]
    r = client.post(f"/api/investments/{b['id']}/payouts", json={
        "date": row["date"], "bank_id": bank["id"], "interest": row["interest"], "principal": row["principal"],
        "tds": 10_00,
    })  # fmt: skip
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["bond"]["schedule"][0]["status"] == "received"
    assert d["value"] == 10_000_00 - row["principal"]
    assert d["bond"]["interest_received"] == row["interest"] and d["bond"]["tds"] == 10_00
    received = row["interest"] - 10_00 + row["principal"]
    assert balance(client, bank["id"]) == 10_000_000 - 10_000_00 + received
    p = d["bond"]["payouts"][0]
    it = client.get(f"/api/transactions/{p['interest_txn_id']}").json()
    assert it["type"] == "deposit" and it["amount"] == row["interest"] - 10_00  # only the interest is income
    assert it["category"]["name"] == "Interest" and it["source"]["name"] == "Acme Finance"
    pt = client.get(f"/api/transactions/{p['principal_txn_id']}").json()
    assert pt["type"] == "transfer" and pt["amount"] == row["principal"]
    assert d["bond"]["unsplit"] == []
    # the same row again is refused
    again = client.post(f"/api/investments/{b['id']}/payouts", json={
        "date": row["date"], "bank_id": bank["id"], "interest": 1, "principal": 0, "n": 1})  # fmt: skip
    assert again.status_code == 422
    # undo removes both entries
    pid = d["bond"]["payouts"][0]["id"]
    u = client.delete(f"/api/investments/{b['id']}/payouts/{pid}").json()
    assert u["value"] == 10_000_00 and u["bond"]["payouts"] == []
    assert balance(client, bank["id"]) == 10_000_000 - 10_000_00


def test_split_an_existing_bank_credit(client, bank):
    b = _new_bond(client, bank)
    row = b["bond"]["schedule"][0]
    total = row["interest"] + row["principal"]
    # recorded as "money back from the bond" for the whole amount (e.g. from a bank statement)
    m = client.post(f"/api/investments/{b['id']}/move", json={
        "direction": "out", "amount": total, "date": row["date"], "bank_id": bank["id"]}).json()  # fmt: skip
    assert len(m["bond"]["unsplit"]) == 1
    tid = m["bond"]["unsplit"][0]["id"]
    bad = client.post(f"/api/investments/{b['id']}/payouts", json={
        "date": row["date"], "bank_id": bank["id"], "interest": row["interest"], "principal": 1,
        "transaction_id": tid})  # fmt: skip
    assert bad.status_code == 422  # doesn't add up to the payment
    r = client.post(f"/api/investments/{b['id']}/payouts", json={
        "date": row["date"], "bank_id": bank["id"], "interest": row["interest"], "principal": row["principal"],
        "transaction_id": tid})  # fmt: skip
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["bond"]["unsplit"] == [] and d["bond"]["schedule"][0]["status"] == "received"
    assert d["value"] == 10_000_00 - row["principal"]
    assert balance(client, bank["id"]) == 10_000_000 - 10_000_00 + total  # bank unchanged by the split
    moved = client.get(f"/api/transactions/{tid}").json()
    assert moved["type"] == "transfer" and moved["amount"] == row["principal"]


def test_interest_only_payout_into_income(client, bank):
    b = _new_bond(client, bank, repayment="bullet")
    row = b["bond"]["schedule"][1]
    assert row["principal"] == 0
    r = client.post(f"/api/investments/{b['id']}/payouts", json={
        "date": row["date"], "bank_id": bank["id"], "interest": row["interest"], "principal": 0})  # fmt: skip
    d = r.json()
    assert d["value"] == 10_000_00 and d["bond"]["schedule"][1]["status"] == "received"
    assert d["bond"]["payouts"][0]["principal_txn_id"] is None


def test_statement_credit_from_issuer_suggests_the_bond():
    from app.modules.investments.matching import score

    inv = SimpleNamespace(
        kind="bond", subtype="ncd", closed_on=None, institution="Acme Finance", person=None, number="INE000A00000",
        fund=None, instalment=None, account=SimpleNamespace(name="Acme Finance Bond"), account_id=7,
    )  # fmt: skip
    hit = score(inv, "NEFT CR-ACME FINANCE LTD-INT AND PRINCIPAL", -1_200_00)
    assert hit is not None and hit.account_id == 7
    assert score(inv, "UPI/SOMEONE/zomato", -1_200_00) is None


def test_face_value_worked_out_from_price_when_not_known(client, bank):
    start = TODAY - timedelta(days=10)
    b = _add(client, kind="bond", subtype="ncd", institution="Acme Finance", quantity=4, amount=40_200_00, rate=11,
             frequency="monthly", repayment="amortising", start_date=str(start),
             maturity_date=str(add_months(start, 12)), money="already")  # fmt: skip
    assert b["face_value"] == 10_050_00  # ₹40,200 for 4 units
    assert b["bond"]["face"] == 40_200_00 and len(b["bond"]["schedule"]) == 12
    r = client.post("/api/investments", json={"kind": "bond", "subtype": "ncd", "rate": 9, "frequency": "monthly",
                                              "start_date": str(start), "maturity_date": str(add_months(start, 6))})  # fmt: skip
    assert r.status_code == 422  # no units

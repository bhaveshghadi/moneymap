"""Loans: EMI 1's interest counted by days from the loan being paid out ("broken period"),
on a 365- or 360-day year, and the EMI worked out so the loan still ends on time."""

from datetime import date

from app.modules.loans.maths import build, build_events, calc_emi, first_emi_interest

LAKH = 100_000 * 100  # ₹1,00,000 in paise
TAKEN = date(2026, 3, 10)
FIRST = date(2026, 5, 5)  # 56 days later


def test_first_emi_interest_by_days():
    # ₹5 lakh at 11%: 5,00,000 × 11% × 56 / 360 = ₹8,555.56 ; / 365 = ₹8,438.36
    assert first_emi_interest(5 * LAKH, 1100, FIRST, TAKEN, "days360") == 8_555_56
    assert first_emi_interest(5 * LAKH, 1100, FIRST, TAKEN, "days365") == 8_438_36
    assert first_emi_interest(5 * LAKH, 1100, FIRST, TAKEN, "month") is None
    assert first_emi_interest(5 * LAKH, 1100, FIRST, None, "days360") is None
    assert first_emi_interest(5 * LAKH, 1100, FIRST, FIRST, "days360") is None


def test_emi_with_first_interest_still_ends_on_time():
    bpi = first_emi_interest(5 * LAKH, 1100, FIRST, TAKEN, "days360")
    emi = calc_emi(5 * LAKH, 1100, 36, bpi)
    assert emi > calc_emi(5 * LAKH, 1100, 36)  # the longer first period costs more
    rows = build(5 * LAKH, 1100, emi, 36, FIRST, first_interest=bpi)
    assert len(rows) == 36 and rows[-1].balance == 0
    assert rows[0].interest == bpi and rows[0].principal == emi - bpi
    assert rows[1].interest == (rows[0].balance * 1100 + 60_000) // 120_000  # then monthly again
    assert abs(rows[-1].emi - emi) < 50_00  # last EMI only a rounding adjustment
    # a normal month's interest gives the usual EMI back
    assert calc_emi(5 * LAKH, 1100, 36, (5 * LAKH * 1100 + 60_000) // 120_000) == calc_emi(5 * LAKH, 1100, 36)


def test_events_schedule_uses_first_interest():
    bpi = first_emi_interest(5 * LAKH, 1100, FIRST, TAKEN, "days365")
    emi = calc_emi(5 * LAKH, 1100, 36, bpi)
    plain = build(5 * LAKH, 1100, emi, 36, FIRST, first_interest=bpi)
    rows, _ = build_events(5 * LAKH, 1100, emi, 36, FIRST, [], first_interest=bpi)
    assert [(r.interest, r.balance) for r in rows] == [(r.interest, r.balance) for r in plain]


def _loan(client, **extra):
    body = {"name": "Personal loan", "kind": "personal", "principal": 5 * LAKH, "rate": 11, "tenure": 36,
            "first_emi_date": FIRST.isoformat(), **extra}
    return client.post("/api/loans", json=body)


def test_api_first_interest(client, bank):
    r = _loan(client, first_interest="days360")
    assert r.status_code == 422 and "taken on" in r.json()["detail"]

    r = _loan(client, first_interest="days360", disbursed_date=TAKEN.isoformat())
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["first_interest"] == "days360" and d["first_interest_days"] == 56
    assert d["schedule"][0]["interest"] == 8_555_56
    assert d["emi"] == calc_emi(5 * LAKH, 1100, 36, 8_555_56)
    assert d["schedule"][-1]["balance"] == 0 and len(d["schedule"]) == 36
    assert d["total_interest"] == sum(x["interest"] for x in d["schedule"])

    # switching to a 365-day year keeps the EMI (it may be the lender's own) and recounts EMI 1
    lid = d["id"]
    r = client.patch(f"/api/loans/{lid}", json={"first_interest": "days365"})
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["emi"] == d["emi"] and e["schedule"][0]["interest"] == 8_438_36

    # back to a month's interest: EMI 1 is a normal month, the taken-on date stays
    r = client.patch(f"/api/loans/{lid}", json={"first_interest": "month"})
    m = r.json()
    assert m["first_interest_days"] is None and m["disbursed_date"] == TAKEN.isoformat()
    assert m["schedule"][0]["interest"] == (5 * LAKH * 1100 + 60_000) // 120_000

    # the lender's EMI is kept as given
    r = _loan(client, name="Lender EMI", first_interest="days360", disbursed_date=TAKEN.isoformat(), emi=17_000_00)
    assert r.json()["emi"] == 17_000_00 and r.json()["schedule"][0]["interest"] == 8_555_56


def test_flat_loan_keeps_the_lenders_emi(client, bank):
    # the formula's EMI: ₹5 lakh flat 11% for 36 months -> (5,00,000 + 1,65,000) / 36 = ₹18,472
    d = _loan(client, method="flat").json()
    assert d["emi"] == 18_472_00 and d["total_interest"] == 1_65_000_00
    # an EMI you enter is what the schedule charges (it used to be ignored)
    d = _loan(client, name="Own EMI", method="flat", emi=17_000_00).json()
    assert {x["emi"] for x in d["schedule"]} == {17_000_00}
    assert d["total_interest"] == 17_000_00 * 36 - 5 * LAKH and d["schedule"][-1]["balance"] == 0


def test_flat_loans_ignore_first_interest(client, bank):
    r = _loan(client, method="flat", first_interest="days360", disbursed_date=TAKEN.isoformat())
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["first_interest_days"] is None
    assert len({x["interest"] for x in d["schedule"][:-1]}) == 1  # flat: same interest every EMI


def test_last_emi_off_suggests_first_interest(client, bank):
    bpi = first_emi_interest(5 * LAKH, 1100, FIRST, TAKEN, "days360")
    lender_emi = calc_emi(5 * LAKH, 1100, 36, bpi)
    # the lender's EMI with a normal month in EMI 1: the last EMI comes out far too small
    d = _loan(client, emi=lender_emi, disbursed_date=TAKEN.isoformat()).json()
    assert d["first_interest"] == "month" and d["last_emi_off"] is True
    assert d["first_interest_suggestion"] == "days360"
    # taking the suggestion keeps the EMI and the last EMI fits
    r = client.patch(f"/api/loans/{d['id']}", json={"first_interest": "days360"})
    e = r.json()
    assert e["emi"] == lender_emi and e["last_emi_off"] is False and e["first_interest_suggestion"] is None
    # without a taken-on date it's still flagged, with nothing to suggest
    d = _loan(client, name="No date", emi=lender_emi).json()
    assert d["last_emi_off"] is True and d["first_interest_suggestion"] is None
    # a worked-out EMI is never flagged
    assert _loan(client, name="Worked out").json()["last_emi_off"] is False

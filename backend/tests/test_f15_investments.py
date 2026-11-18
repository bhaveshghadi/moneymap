"""F15 Investments (step 1: by hand) — value rules, money in / out, net worth, coming up."""

from datetime import date, timedelta
from types import SimpleNamespace

from app.core.dates import add_months
from app.modules.investments.values import Rates, growth, value_of

from .helpers import balance

TODAY = date.today()


def _inv(**kw):
    base = dict(
        kind="other", subtype=None, rate_bp=None, compounding=None, start_date=None, maturity_date=None, months=None,
        instalment=None, frequency=None, sum_assured=None, maturity_amount=None, quantity=None, purity=None,
        unit_price=None, current_value=None, value_date=None, payout_on=None, payout_amount=None,
    )  # fmt: skip
    return SimpleNamespace(**{**base, **kw})


# ---------------------------------------------------------------- value rules (pure)


def test_growth_compounding():
    d0, d1 = date(2025, 1, 1), date(2026, 1, 1)
    assert growth(100_000_00, 700, "yearly", d0, d1) == 107_000_00
    assert growth(100_000_00, 700, "quarterly", d0, d1) == round(100_000_00 * 1.0175**4)
    assert growth(100_000_00, 1200, "simple", d0, d1) == 112_000_00
    assert growth(100_000_00, 700, "payout", d0, d1) == 100_000_00
    assert growth(100_000_00, 700, "quarterly", d1, d0) == 100_000_00  # nothing before it was put in


def test_fd_grows_until_maturity_then_stops():
    fd = _inv(kind="fd", rate_bp=700, compounding="yearly", start_date=date(2024, 1, 1), maturity_date=date(2025, 1, 1))
    entries = [(date(2024, 1, 1), 100_000_00)]
    mid = value_of(fd, entries, date(2024, 7, 2), Rates())
    after = value_of(fd, entries, date(2026, 6, 1), Rates())
    assert 100_000_00 < mid.value < 107_000_00
    expected = growth(100_000_00, 700, "yearly", date(2024, 1, 1), date(2025, 1, 1))
    assert after.value == after.maturity_value == expected  # no interest after maturity
    assert after.invested == 100_000_00 and after.gain == expected - 100_000_00
    assert after.dues[0].what == "matures"


def test_post_office_defaults_scss_pays_out():
    scss = _inv(kind="post_office", subtype="scss", rate_bp=820, start_date=date(2024, 1, 1),
                maturity_date=date(2029, 1, 1))  # fmt: skip
    v = value_of(scss, [(date(2024, 1, 1), 500_000_00)], date(2026, 1, 1), Rates())
    assert v.value == 500_000_00  # interest is paid out to the bank
    nsc = _inv(kind="post_office", subtype="nsc", rate_bp=770, start_date=date(2024, 1, 1),
               maturity_date=date(2029, 1, 1))  # fmt: skip
    v = value_of(nsc, [(date(2024, 1, 1), 100_000_00)], date(2025, 1, 1), Rates())
    assert v.value == growth(100_000_00, 770, "yearly", date(2024, 1, 1), date(2025, 1, 1))


def test_rd_schedule():
    rd = _inv(kind="rd", rate_bp=650, start_date=date(2025, 1, 5), months=12, instalment=5_000_00)
    v = value_of(rd, [], date(2025, 4, 10), Rates())
    assert (v.paid_count, v.total_count) == (4, 12)
    assert v.invested == 20_000_00 and v.value > 20_000_00
    assert v.dues[0].date == date(2026, 1, 5)  # maturity = start + months
    assert v.maturity_value > 60_000_00


def test_insurance_premiums_and_term():
    pol = _inv(kind="insurance", subtype="endowment", start_date=date(2020, 3, 1), frequency="yearly", months=120,
               instalment=25_000_00, maturity_date=date(2035, 3, 1), maturity_amount=5_00_000_00)  # fmt: skip
    v = value_of(pol, [], date(2026, 2, 1), Rates())
    assert (v.paid_count, v.total_count) == (6, 10)
    assert v.value == v.invested == 6 * 25_000_00  # no surrender value entered
    assert v.dues[0].what == "premium" and v.dues[0].date == date(2026, 3, 1)
    pol.current_value, pol.value_date = 1_20_000_00, date(2026, 1, 1)
    assert value_of(pol, [], date(2026, 2, 1), Rates()).value == 1_20_000_00
    term = _inv(kind="insurance", subtype="term", start_date=date(2020, 3, 1), frequency="yearly", months=240,
                instalment=12_000_00)  # fmt: skip
    tv = value_of(term, [], date(2026, 2, 1), Rates())
    assert tv.value == tv.invested == tv.gain == 0 and tv.paid_count == 6


def test_chit_before_and_after_payout():
    chit = _inv(kind="chit", start_date=date(2025, 1, 10), months=20, instalment=10_000_00)
    v = value_of(chit, [], date(2025, 5, 15), Rates())
    assert v.value == v.invested == 5 * 10_000_00
    chit.payout_on, chit.payout_amount = date(2025, 5, 15), 1_80_000_00
    v = value_of(chit, [], date(2025, 5, 15), Rates())
    assert v.owed == 15 * 10_000_00 and v.value == -15 * 10_000_00  # what's left to pay
    # gain = payout - all instalments
    assert v.gain == 1_80_000_00 - 20 * 10_000_00


def test_money_lent_simple_interest_and_repayment():
    lent = _inv(kind="lent", rate_bp=1200, start_date=date(2025, 1, 1), maturity_date=date(2025, 7, 1))
    entries = [(date(2025, 1, 1), 1_00_000_00), (date(2026, 1, 1), -50_000_00)]
    v = value_of(lent, entries, date(2026, 1, 1), Rates())
    assert v.value == 1_12_000_00 - 50_000_00  # interest keeps running after the due date
    assert v.invested == 50_000_00
    assert v.dues[0].what == "due_back"


def test_gold_by_purity_and_no_rate():
    ring = _inv(kind="gold", subtype="jewellery", quantity=10_000, purity="22k")  # 10 g
    assert value_of(ring, [], TODAY, Rates()).no_price
    v = value_of(ring, [], TODAY, Rates(gold_24k=7_200_00, on=TODAY))
    assert v.value == round(10_000 * 7_200_00 * 22 / 24 / 1000)
    sgb = _inv(kind="gold", subtype="sgb", quantity=5_000, purity="22k")  # SGB is always 24k
    assert value_of(sgb, [], TODAY, Rates(gold_24k=7_200_00, on=TODAY)).value == 36_000_00
    silver = _inv(kind="gold", subtype="silver", quantity=100_000, purity="999")
    assert value_of(silver, [], TODAY, Rates(silver=90_00, on=TODAY)).value == 9_000_00
    old = value_of(ring, [], TODAY, Rates(gold_24k=7_200_00, on=TODAY - timedelta(days=91)))
    assert old.stale


def test_stocks_and_entered_values():
    s = _inv(kind="stocks", subtype="stock", quantity=10_000, unit_price=1_500_00, value_date=TODAY)
    v = value_of(s, [(date(2025, 1, 1), 12_000_00)], TODAY, Rates())
    assert v.value == 15_000_00 and v.gain == 3_000_00
    ppf = _inv(kind="retirement", subtype="ppf", current_value=4_00_000_00, value_date=TODAY - timedelta(days=200))
    v = value_of(ppf, [], TODAY, Rates())
    assert v.value == 4_00_000_00 and v.stale


# ---------------------------------------------------------------- API


def _add(client, **body):
    r = client.post("/api/investments", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_add_fd_from_bank_is_a_transfer(client, bank):
    start = TODAY - timedelta(days=100)
    fd = _add(client, kind="fd", institution="SBI", amount=50_000_00, rate=7, compounding="quarterly",
              start_date=str(start), maturity_date=str(add_months(start, 12)), money="bank",
              pay_from_id=bank["id"])  # fmt: skip
    assert fd["name"] == "SBI Fixed deposit"
    assert fd["invested"] == 50_000_00 and fd["value"] > 50_000_00
    assert len(fd["moves"]) == 1 and fd["moves"][0]["type"] == "transfer"
    assert balance(client, bank["id"]) == 10_000_000 - 50_000_00
    ov = client.get("/api/overview").json()
    assert ov["spending"] == 0  # not spending
    assert ov["investments_value"] == fd["value"]
    assert ov["net_worth"] == 10_000_000 - 50_000_00 + fd["value"]
    # the investment's account can't be changed on the Accounts page
    assert client.patch(f"/api/accounts/{fd['id']}", json={"name": "x"}).status_code == 422


def test_already_invested_uses_opening_balance(client, bank):
    p = _add(client, kind="property", name="Plot", amount=20_00_000_00, start_date="2020-01-01",
             current_value=35_00_000_00)  # fmt: skip
    assert p["opening"] == 20_00_000_00 and p["moves"] == []
    assert p["value"] == 35_00_000_00 and p["gain"] == 15_00_000_00
    assert balance(client, bank["id"]) == 10_000_000


def test_kind_checks(client):
    assert client.post("/api/investments", json={"kind": "fd", "amount": 100}).status_code == 422
    assert client.post("/api/investments", json={"kind": "post_office", "subtype": "xyz"}).status_code == 422
    r = client.post("/api/investments", json={"kind": "rd", "instalment": 100, "start_date": str(TODAY)})
    assert r.status_code == 422  # months and rate missing
    r = client.post("/api/investments", json={"kind": "gold", "subtype": "jewellery"})
    assert r.status_code == 422


def test_money_in_out_close_reopen_delete(client, bank):
    lent = _add(client, kind="lent", person="Ravi", amount=1_00_000, start_date=str(TODAY - timedelta(days=10)),
                money="bank", pay_from_id=bank["id"])  # fmt: skip
    assert lent["name"] == "Lent to Ravi"
    assert lent["moves"][0]["description"] == "Lent to Ravi"
    r = client.post(f"/api/investments/{lent['id']}/move",
                    json={"direction": "out", "amount": 40_000, "date": str(TODAY), "bank_id": bank["id"]})  # fmt: skip
    assert r.status_code == 200, r.text
    assert r.json()["invested"] == 60_000
    r = client.post(f"/api/investments/{lent['id']}/close",
                    json={"date": str(TODAY), "amount": 60_000, "bank_id": bank["id"]})  # fmt: skip
    closed = r.json()
    assert closed["status"] == "closed" and closed["value"] == 0 and closed["invested"] == 0
    assert balance(client, bank["id"]) == 10_000_000
    assert client.get("/api/overview").json()["investments_value"] == 0
    assert client.post(f"/api/investments/{lent['id']}/reopen").json()["status"] == "active"
    assert client.delete(f"/api/investments/{lent['id']}").status_code == 204
    assert client.get(f"/api/investments/{lent['id']}").status_code == 404
    assert balance(client, bank["id"]) == 10_000_000
    txns = client.get("/api/transactions").json()
    assert not (txns["items"] if isinstance(txns, dict) else txns)


def test_update_price_sets_value_date(client):
    s = _add(client, kind="stocks", subtype="stock", name="INFY", quantity=10, amount=15_000_00)
    assert s["no_price"] and s["value"] == 15_000_00
    r = client.patch(f"/api/investments/{s['id']}", json={"unit_price": 1_800_00})
    v = r.json()
    assert v["value"] == 18_000_00 and v["value_date"] == str(TODAY) and not v["no_price"]


def test_rates_and_gold(client):
    g = _add(client, kind="gold", subtype="coin", quantity=10)
    assert g["purity"] == "24k" and g["no_price"]
    r = client.put("/api/investments/rates", json={"gold_24k": 7_000_00, "silver": 90_00})
    assert r.json()["date"] == str(TODAY)
    assert client.get(f"/api/investments/{g['id']}").json()["value"] == 70_000_00


def test_coming_up_and_summary(client, bank):
    start = add_months(TODAY, -11)
    _add(client, kind="fd", amount=10_000_00, rate=7, start_date=str(start),
         maturity_date=str(TODAY + timedelta(days=10)))  # fmt: skip
    _add(client, kind="chit", start_date=str(add_months(TODAY, -2) + timedelta(days=3)), months=10,
         instalment=5_000_00)  # fmt: skip
    _add(client, kind="property", amount=1_00_000_00)  # nothing coming up
    s = client.get("/api/investments/summary").json()
    whats = [d["what"] for d in s["dues"]]
    assert "matures" in whats and "instalment" in whats
    assert s["count"] == 3 and {k["kind"] for k in s["by_kind"]} == {"fd", "chit", "property"}
    ov = client.get("/api/overview").json()
    assert len(ov["investment_dues"]) == 2

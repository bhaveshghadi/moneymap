"""F10 Rules — conditions, actions, order / stop, fill-blanks on new transactions, test and apply to
existing, suggestions, statement import ("rule for next time") and the Inbox pre-fill."""

from types import SimpleNamespace

from app.modules.rules.engine import Probe, condition_matches, plan_for

from .helpers import cat_id, spend
from .test_statement_import import ICICI_LINES, PASSWORD, add_email


def _p(**kw):
    base = dict(type="withdrawal", amount=45_000, description="UPI/SWIGGY/swiggy@ybl/food", payee="Swiggy",
                account_ids={1}, category_id=None, tags=set())  # fmt: skip
    return Probe(**{**base, **kw})


def _rule(conditions, actions, match_all=True, stop=False, title="r"):
    return SimpleNamespace(conditions=conditions, actions=actions, match_all=match_all, stop=stop, title=title)


def test_conditions():
    p = _p()
    c = lambda t, v=None: condition_matches(p, {"type": t, "value": v})  # noqa: E731
    assert c("description_contains", "  SWIGGY ")  # case and spaces ignored
    assert c("description_starts", "upi/") and not c("description_starts", "swiggy")
    assert c("description_is", "upi/swiggy/swiggy@ybl/food")
    assert c("payee_contains", "swig")
    assert c("amount_is", 45_000) and c("amount_more", 40_000) and c("amount_less", 50_000)
    assert not c("amount_more", 45_000)
    assert c("type_is", "withdrawal") and not c("type_is", "deposit")
    assert c("account_is", 1) and not c("account_is", 2)
    assert c("no_category")
    assert not c("has_tag", "work") and condition_matches(_p(tags={"work"}), {"type": "has_tag", "value": "Work"})


def test_all_or_any_order_and_stop():
    food = _rule([{"type": "payee_contains", "value": "swiggy"}], [{"type": "set_category", "value": 1}], title="A")
    other = _rule([{"type": "amount_more", "value": 1}], [{"type": "set_category", "value": 2},
                                                          {"type": "add_tag", "value": "x"}], title="B")  # fmt: skip
    plan = plan_for(_p(), [food, other])
    assert plan.category_id == 1 and plan.add_tags == ["x"]  # the first rule's category wins
    food.stop = True
    assert plan_for(_p(), [food, other]).add_tags == []  # stopped after A
    either = _rule([{"type": "payee_contains", "value": "zomato"}, {"type": "amount_less", "value": 50_000}],
                   [{"type": "add_tag", "value": "y"}], match_all=False)  # fmt: skip
    assert plan_for(_p(), [either]).add_tags == ["y"]
    either.match_all = True
    assert not plan_for(_p(), [either]).rules
    assert not plan_for(_p(), [_rule([], [{"type": "add_tag", "value": "z"}])]).rules  # no conditions: never


def _make(client, conditions, actions, **extra):
    r = client.post("/api/rules", json={"title": "Test rule", "conditions": conditions, "actions": actions, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_rule_validation(client):
    bad = client.post(
        "/api/rules",
        json={"title": "x", "conditions": [{"type": "nope"}], "actions": [{"type": "add_tag", "value": "a"}]},
    )
    assert bad.status_code == 422
    bad = client.post("/api/rules", json={"title": "x", "conditions": [{"type": "payee_contains", "value": " "}],
                                          "actions": [{"type": "add_tag", "value": "a"}]})  # fmt: skip
    assert bad.status_code == 422
    bad = client.post("/api/rules", json={"title": "x", "conditions": [{"type": "payee_contains", "value": "a"}],
                                          "actions": [{"type": "set_category", "value": 99999}]})  # fmt: skip
    assert bad.status_code == 422


def test_new_transactions_fill_blanks_only(client, bank):
    food, travel = cat_id(client, "Dining"), cat_id(client, "Travel")
    _make(client, [{"type": "payee_contains", "value": "swiggy"}],
          [{"type": "set_category", "value": food}, {"type": "add_tag", "value": "delivery"},
           {"type": "set_payee", "value": "Swiggy India"}])  # fmt: skip
    t = spend(client, bank, 45_000, payee="SWIGGY BLR")  # no category chosen
    assert t["category"]["id"] == food and t["tags"] == ["delivery"]
    assert t["destination"]["name"] == "SWIGGY BLR"  # your payee is kept on a new transaction
    t2 = spend(client, bank, 45_000, payee="SWIGGY BLR", category_id=travel)  # you chose one
    assert t2["category"]["id"] == travel and t2["tags"] == ["delivery"]


def test_order_move_and_toggle(client):
    a = _make(client, [{"type": "payee_contains", "value": "a"}], [{"type": "add_tag", "value": "a"}])
    b = _make(client, [{"type": "payee_contains", "value": "b"}], [{"type": "add_tag", "value": "b"}])
    assert [r["id"] for r in client.get("/api/rules").json()] == [a["id"], b["id"]]
    moved = client.post(f"/api/rules/{b['id']}/move", json={"direction": "up"}).json()
    assert [r["id"] for r in moved] == [b["id"], a["id"]]
    assert client.patch(f"/api/rules/{a['id']}", json={"active": False}).json()["active"] is False
    assert client.delete(f"/api/rules/{b['id']}").status_code == 204
    assert [r["position"] for r in client.get("/api/rules").json()] == [0]


def test_test_and_apply_to_existing(client, bank):
    food, travel = cat_id(client, "Dining"), cat_id(client, "Travel")
    spend(client, bank, 30_000, payee="Swiggy")
    spend(client, bank, 20_000, payee="Swiggy", category_id=travel)
    spend(client, bank, 10_000, payee="Zomato")
    body = {"title": "Swiggy", "conditions": [{"type": "payee_contains", "value": "swiggy"}],
            "actions": [{"type": "set_category", "value": food}]}  # fmt: skip
    t = client.post("/api/rules/test", json=body).json()
    assert t["matched"] == 2 and t["would_change"] == 1  # the one you put in Travel is left (fill blanks)
    assert client.post("/api/rules/test?overwrite=true", json=body).json()["would_change"] == 2
    rule = _make(client, body["conditions"], body["actions"])
    out = client.post(f"/api/rules/{rule['id']}/apply", json={"overwrite": False}).json()
    assert out == {"matched": 2, "changed": 1}
    out = client.post(f"/api/rules/{rule['id']}/apply", json={"overwrite": True}).json()
    assert out == {"matched": 2, "changed": 1}
    cats = {
        x["category"]["id"]
        for x in client.get("/api/transactions").json()["items"]
        if x["destination"]["name"] == "Swiggy"
    }
    assert cats == {food}


def test_rename_payee_when_applying(client, bank):
    spend(client, bank, 30_000, payee="UPI-SWIGGY-BLR")
    rule = _make(client, [{"type": "payee_contains", "value": "swiggy"}], [{"type": "set_payee", "value": "Swiggy"}])
    assert client.post(f"/api/rules/{rule['id']}/apply", json={"overwrite": False}).json()["changed"] == 0
    assert client.post(f"/api/rules/{rule['id']}/apply", json={"overwrite": True}).json()["changed"] == 1
    assert client.get("/api/transactions").json()["items"][0]["destination"]["name"] == "Swiggy"


def test_suggestions(client, bank):
    food = cat_id(client, "Dining")
    for _ in range(3):
        spend(client, bank, 30_000, payee="Swiggy", category_id=food)
    spend(client, bank, 30_000, payee="Zomato", category_id=food)  # only once
    (s,) = client.get("/api/rules/suggestions").json()
    assert (s["payee"], s["category_id"], s["count"]) == ("Swiggy", food, 3)
    _make(client, [{"type": "payee_contains", "value": "swiggy"}], [{"type": "set_category", "value": food}])
    assert client.get("/api/rules/suggestions").json() == []  # covered by a rule now


def test_statement_rows_use_rules_and_rule_for_next_time(client):
    acct = client.post("/api/accounts", json={"name": "ICICI Savings", "type": "asset", "account_number": "XXXX2840",
                                              "opening_balance": 5_000_000}).json()  # fmt: skip
    client.post("/api/accounts", json={"name": "Wallet", "type": "cash"})
    food, groceries = cat_id(client, "Dining"), cat_id(client, "Groceries")
    _make(client, [{"type": "description_contains", "value": "swiggy"}],
          [{"type": "set_category", "value": food}, {"type": "set_payee", "value": "Swiggy"},
           {"type": "add_tag", "value": "delivery"}])  # fmt: skip
    d = client.post("/api/statements", json={"attachment_id": add_email(ICICI_LINES), "password": PASSWORD}).json()
    sw = next(r for r in d["rows"] if "SWIGGY" in r["raw"])
    assert sw["category_id"] == food and sw["payee"] == "Swiggy" and sw["suggestion_kind"] == "rule"
    zepto = next(r for r in d["rows"] if "ZEPTO" in r["raw"])
    base = f"/api/statements/{d['id']}/rows"
    r = client.patch(f"{base}/{zepto['id']}", json={"category_id": groceries, "create_rule": True})
    assert r.json()["rule_keyword"] == zepto["payee"]
    for row in d["rows"]:  # everything else: leave uncategorised so the statement can be imported
        if row["id"] not in (sw["id"], zepto["id"]) and row["kind"] != "transfer" and row["category_id"] is None:
            client.patch(f"{base}/{row['id']}", json={"leave_uncategorised": True})
        if row["kind"] == "transfer" and not row["transfer_account_id"]:
            client.patch(f"{base}/{row['id']}", json={"include": False})
    out = client.post(f"/api/statements/{d['id']}/import")
    assert out.status_code == 200, out.text
    assert out.json()["rules_created"] == 1
    rules = client.get("/api/rules").json()
    made = rules[-1]
    assert made["conditions"][0] == {"type": "payee_contains", "value": zepto["payee"]}
    assert made["actions"] == [{"type": "set_category", "value": groceries}]
    txns = client.get("/api/transactions").json()["items"]
    swiggy = next(t for t in txns if t["destination"]["name"] == "Swiggy")
    assert swiggy["tags"] == ["delivery"]  # the rule's tag is added on import
    assert acct["id"]


def test_inbox_prefill_uses_rules(client):
    from datetime import datetime

    from app.db import SessionLocal
    from app.modules.gmail.models import GmailMessage

    food = cat_id(client, "Dining")
    _make(client, [{"type": "payee_contains", "value": "swiggy"}],
          [{"type": "set_category", "value": food}, {"type": "set_payee", "value": "Swiggy"}])  # fmt: skip
    with SessionLocal() as db:
        db.add(GmailMessage(id="alert1", from_addr="alerts@hdfcbank.net", subject="You have done a UPI txn",
                            body_text="Rs.450.00 has been debited from account **1234 to VPA swiggy@ybl SWIGGY on 12-11-26.",
                            sent_at=datetime(2026, 11, 12), status="new"))  # fmt: skip
        db.commit()
    s = client.get("/api/inbox/alert1").json()["suggestion"]
    assert s is not None  # the alert reader understood the email
    assert s["category_id"] == food and s["payee"] == "Swiggy" and s["rule"]

"""Several Gmail accounts under one Google client: connect, search each, the same email in two
accounts fetched once, Inbox per account, disconnect / remove. Every address and email is made up."""

from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pytest

from app.modules.gmail import client as gclient
from app.modules.gmail import fetch as gfetch

from .test_gmail import CLIENT_JSON, PDF, FakeGmail, make_msg

A, B = "me@example.com", "work@example.com"


def with_id(msg: dict, rfc: str) -> dict:
    msg["payload"]["headers"].append({"name": "Message-ID", "value": rfc})
    return msg


@pytest.fixture()
def boxes(client, monkeypatch):
    """Two fake mailboxes. The statement <same@bank> reached both."""
    a = FakeGmail(
        [
            with_id(make_msg("a1", "Your HDFC Bank statement", "HDFC Bank <alerts@hdfcbank.net>", datetime(2026, 11, 2, 9),
                             attachments=[("stmt.pdf", "application/pdf", PDF)]), "<same@bank>"),
            with_id(make_msg("a2", "Swiggy order delivered", "Swiggy <noreply@swiggy.in>", datetime(2026, 11, 3, 21),
                             body_text="Order total 450"), "<a2@swiggy>"),
        ],
        {"a1-a0": PDF},
    )  # fmt: skip
    b = FakeGmail(
        [
            with_id(make_msg("b1", "Your HDFC Bank statement", "HDFC Bank <alerts@hdfcbank.net>", datetime(2026, 11, 2, 9),
                             attachments=[("stmt.pdf", "application/pdf", PDF)]), "<same@bank>"),
            with_id(make_msg("b3", "Swiggy order delivered", "Swiggy <noreply@swiggy.in>", datetime(2026, 11, 9, 13),
                             body_text="Order total 300"), "<b3@swiggy>"),
        ],
        {"b1-a0": PDF},
    )  # fmt: skip
    a.profile = lambda: {"emailAddress": A}
    b.profile = lambda: {"emailAddress": B}
    signing_in = {"who": a}

    def api_for(db, mailbox=None):
        if mailbox is None or mailbox.email is None:  # the account just signed in
            return signing_in["who"]
        return a if mailbox.email == A else b

    monkeypatch.setattr(gclient, "api_for", api_for)
    monkeypatch.setattr(gfetch, "RUN_INLINE", True)
    monkeypatch.setattr(
        gclient, "http_post",
        lambda url, data: {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": gclient.SCOPE},
    )  # fmt: skip
    assert client.put("/api/gmail/client", json={"json_text": CLIENT_JSON}).status_code == 200

    def connect(who):
        signing_in["who"] = who
        r = client.post("/api/gmail/connect", json={"origin": "http://localhost:9009"}).json()
        state = parse_qs(urlparse(r["url"]).query)["state"][0]
        client.get("/api/gmail/callback", params={"code": "c", "state": state})

    connect(a)
    connect(b)
    return {"a": a, "b": b, "connect": connect}


def _ids(st):
    return {m["email"]: m["id"] for m in st["mailboxes"]}


def estimate(client, **kw):
    body = {"template_ids": ["hdfc-bank-account-statement"], "custom": ["from:swiggy.in"],
            "date_from": "2026-11-01", "date_to": "2026-11-30", **kw}  # fmt: skip
    r = client.post("/api/gmail/estimate", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_two_accounts_connected(client, boxes):
    st = client.get("/api/gmail/status").json()
    assert [(m["email"], m["connected"]) for m in st["mailboxes"]] == [(A, True), (B, True)]
    assert st["connected"] and st["email"] == A
    boxes["connect"](boxes["a"])  # the same address again: its token is replaced, not a third account
    assert len(client.get("/api/gmail/status").json()["mailboxes"]) == 2


def test_search_both_and_same_email_once(client, boxes):
    st = client.get("/api/gmail/status").json()
    ids = _ids(st)
    est = estimate(client)
    assert sorted(est["mailbox_ids"]) == sorted(ids.values())
    found = {f["id"]: f for f in est["found"]}
    assert set(found) == {"a1", "a2", "b1", "b3"}
    assert found["b1"]["dup"] == A and found["b1"]["known"] is True  # the same statement, already found in A
    assert found["a1"]["mailbox"] == A and found["b3"]["mailbox"] == B
    assert est["new_count"] == 3
    client.post(f"/api/gmail/runs/{est['id']}/start", json={})

    page = client.get("/api/inbox").json()
    assert page["total"] == 3
    by_id = {i["id"]: i for i in page["items"]}
    assert by_id["a1"]["mailbox_email"] == A and by_id["b3"]["mailbox_email"] == B
    only_b = client.get("/api/inbox", params={"mailbox_id": ids[B]}).json()
    assert [i["id"] for i in only_b["items"]] == ["b3"]
    st = client.get("/api/gmail/status").json()
    assert {m["email"]: m["emails"] for m in st["mailboxes"]} == {A: 2, B: 1}
    assert all(m["last_fetch_to"] == "2026-11-30" for m in st["mailboxes"])

    # fetched already: nothing new, and the copy in B still isn't fetched
    again = estimate(client)
    assert again["new_count"] == 0 and {f["id"]: f["known"] for f in again["found"]}["b1"] is True


def test_search_one_account(client, boxes):
    ids = _ids(client.get("/api/gmail/status").json())
    est = estimate(client, mailbox_ids=[ids[B]])
    assert est["mailbox_ids"] == [ids[B]] and {f["id"] for f in est["found"]} == {"b1", "b3"}
    assert boxes["a"].queries == []  # A wasn't searched
    assert client.post("/api/gmail/estimate", json={
        "template_ids": ["hdfc-bank-account-statement"], "date_from": "2026-11-01", "date_to": "2026-11-30",
        "mailbox_ids": [999],
    }).status_code == 422  # fmt: skip


def test_disconnect_and_remove_one(client, boxes, monkeypatch):
    monkeypatch.setattr(gclient.httpx, "post", lambda *a, **k: None)  # don't call Google to revoke
    ids = _ids(client.get("/api/gmail/status").json())
    est = estimate(client, mailbox_ids=[ids[B]])
    client.post(f"/api/gmail/runs/{est['id']}/start", json={})

    assert client.delete(f"/api/gmail/mailboxes/{ids[B]}").status_code == 422  # still connected
    st = client.post("/api/gmail/disconnect", json={"mailbox_id": ids[B]}).json()
    assert {m["email"]: m["connected"] for m in st["mailboxes"]} == {A: True, B: False}
    assert st["connected"] is True
    est = estimate(client)
    assert est["mailbox_ids"] == [ids[A]]  # only the connected one is searched

    st = client.delete(f"/api/gmail/mailboxes/{ids[B]}").json()
    assert [m["email"] for m in st["mailboxes"]] == [A]
    page = client.get("/api/inbox").json()
    assert page["total"] == 2 and all(i["mailbox_email"] is None for i in page["items"])  # B's emails stay

    st = client.post("/api/gmail/disconnect", json={}).json()  # all
    assert st["connected"] is False and st["email"] is None

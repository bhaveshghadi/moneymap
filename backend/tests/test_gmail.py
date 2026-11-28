"""Gmail import (fetch-only) + Inbox + transaction alert emails, against a fake Gmail."""

import base64
import json
import sqlite3
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import get_settings
from app.modules.gmail import client as gclient
from app.modules.gmail import fetch as gfetch
from app.modules.gmail.alerts import parse_alert

from .helpers import spend

CLIENT_JSON = json.dumps({"installed": {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "s3cret",
                                        "redirect_uris": ["http://localhost"]}})


def b64(s: bytes | str) -> str:
    return base64.urlsafe_b64encode(s.encode() if isinstance(s, str) else s).decode().rstrip("=")


def make_msg(mid, subject, sender, when: datetime, body_html=None, body_text=None, attachments=()):
    parts = []
    if body_text:
        parts.append({"mimeType": "text/plain", "body": {"data": b64(body_text)}})
    if body_html:
        parts.append({"mimeType": "text/html", "body": {"data": b64(body_html)}})
    for i, (name, mime, data) in enumerate(attachments):
        parts.append({"mimeType": mime, "filename": name, "body": {"attachmentId": f"{mid}-a{i}", "size": len(data)}})
    return {
        "id": mid, "threadId": f"t-{mid}", "snippet": f"{subject} &amp; more", "sizeEstimate": 50_000,
        "internalDate": str(int(when.timestamp() * 1000)),
        "payload": {"mimeType": "multipart/mixed", "headers": [{"name": "From", "value": sender},
                                                                 {"name": "Subject", "value": subject}], "parts": parts},
    }


class FakeGmail:
    """Matches queries by a 'from:' domain substring, like a tiny Gmail."""

    def __init__(self, messages, attachments):
        self.messages = {m["id"]: m for m in messages}
        self.attachments = attachments
        self.queries: list[str] = []
        self.full_gets: list[str] = []

    def profile(self):
        return {"emailAddress": "me@example.com"}

    def list_ids(self, q):
        self.queries.append(q)
        out = []
        for m in self.messages.values():
            sender = m["payload"]["headers"][0]["value"].lower()
            has_pdf = any(p.get("filename") for p in m["payload"]["parts"])
            if "-filename:pdf" in q and has_pdf:
                continue
            if "has:attachment" in q and not has_pdf:
                continue
            if any(dom in q.lower() and dom in sender for dom in ("hdfcbank", "swiggy", "sbicard")):
                out.append(m["id"])
        return out

    def get_message(self, mid, fmt="full"):
        if fmt == "full":
            self.full_gets.append(mid)
        return self.messages[mid]

    def get_attachment(self, mid, aid):
        return self.attachments[aid]


PDF = b"%PDF-1.4 fake statement"


@pytest.fixture()
def fake(monkeypatch):
    msgs = [
        make_msg("m1", "Your HDFC Bank statement", "HDFC Bank <alerts@hdfcbank.net>", datetime(2026, 11, 2, 9),
                 body_text="Dear customer, your statement is attached.", attachments=[("stmt.pdf", "application/pdf", PDF)]),
        make_msg("m2", "Swiggy order delivered", "Swiggy <noreply@swiggy.in>", datetime(2026, 11, 3, 21),
                 body_html="<html><style>.x{}</style><p>Order total <b>₹450</b></p><br>Thanks!</html>"),
        make_msg("m3", "HDFC statement (copy)", "HDFC Bank <alerts@hdfcbank.net>", datetime(2026, 11, 4, 9),
                 attachments=[("same.pdf", "application/pdf", PDF)]),  # identical bytes to m1's PDF
        make_msg("m4", "Alert : Update on your HDFC Bank A/c", "HDFC Bank <alerts@hdfcbank.net>",
                 datetime(2026, 11, 12, 19),
                 body_text="Dear Customer, Rs.450.00 has been debited from account **1234 to VPA swiggy@icici on 12-11-26."),
    ]
    g = FakeGmail(msgs, {"m1-a0": PDF, "m3-a0": PDF})
    monkeypatch.setattr(gclient, "api_for", lambda db, mailbox=None: g)
    monkeypatch.setattr(gfetch, "RUN_INLINE", True)
    return g


@pytest.fixture()
def connected(client, fake, monkeypatch):
    assert client.put("/api/gmail/client", json={"json_text": CLIENT_JSON}).status_code == 200
    calls = []

    def fake_post(url, data):
        calls.append((url, data))
        return {"access_token": "at-SECRET", "refresh_token": "rt-SECRET", "expires_in": 3600, "scope": gclient.SCOPE}

    monkeypatch.setattr(gclient, "http_post", fake_post)
    r = client.post("/api/gmail/connect", json={"origin": "http://localhost:9009"}).json()
    client.get("/api/gmail/callback", params={"code": "c", "state": parse_qs(urlparse(r["url"]).query)["state"][0]})
    return calls


# ---------------------------------------------------------------- units


def test_client_json_validation():
    assert gclient.parse_client_json(CLIENT_JSON) == ("123-abc.apps.googleusercontent.com", "s3cret")
    with pytest.raises(gclient.GmailError, match="Web application"):
        gclient.parse_client_json(json.dumps({"web": {"client_id": "a", "client_secret": "b"}}))
    with pytest.raises(gclient.GmailError, match="valid JSON"):
        gclient.parse_client_json("not json")


def test_redirect_uri_loopback_vs_remote():
    assert gclient.redirect_uri_for("http://localhost:9009") == ("http://localhost:9009/api/gmail/callback", True)
    assert gclient.redirect_uri_for("http://127.0.0.1:9009") == ("http://127.0.0.1:9009/api/gmail/callback", True)
    uri, direct = gclient.redirect_uri_for("http://moneymap.home.lan:9009")
    assert uri == "http://127.0.0.1:9009/api/gmail/callback" and direct is False


def test_build_queries_statements_and_alerts():
    qs = gfetch.build_queries(["hdfc-bank-account-statement", "hdfc-bank-transaction-alerts"], ["from:swiggy.in"],
                              date(2026, 11, 1), date(2026, 11, 30))
    assert qs[0]["label"] == "HDFC Bank" and qs[0]["doc_type"] == "bank_statement"
    assert "after:2026/11/01" in qs[0]["query"] and "before:2026/12/01" in qs[0]["query"]
    assert qs[0]["query"].count("-in:spam") == 1  # pack fragments + base exclusions de-duplicated
    assert qs[1]["label"] == "HDFC Bank · alerts" and qs[1]["doc_type"] == "transaction_alert"
    assert "-filename:pdf" in qs[1]["query"] and "debited" in qs[1]["query"]
    assert qs[2]["query"].startswith("from:swiggy.in -in:spam") and qs[2]["doc_type"] is None
    with pytest.raises(gclient.GmailError, match="Leave dates out"):
        gfetch.build_queries([], ["from:x after:2020/01/01"], date(2026, 1, 1), date(2026, 1, 2))
    with pytest.raises(gclient.GmailError, match="at least one"):
        gfetch.build_queries([], ["  "], date(2026, 1, 1), date(2026, 1, 2))


def test_provider_list_statements_first_alerts_last(client):
    providers = client.get("/api/gmail/providers").json()
    kinds = [p["kind"] for p in providers]
    # statements (bank, card, loan, mutual fund) come first; the optional alert templates last
    first_alert = kinds.index("transaction_alert")
    assert set(kinds[first_alert:]) == {"transaction_alert"}
    assert {"bank_statement", "credit_card_statement", "loan_statement", "mf_statement"} == set(kinds[:first_alert])
    assert any(p["id"] == "hdfc-bank-transaction-alerts" and p["doc_type"] == "Transaction alerts" for p in providers)
    loans = {p["id"]: p for p in providers if p["kind"] == "loan_statement"}
    assert loans["bajaj-finance-loan-statement"]["name"] == "Bajaj Finance"  # lender not in the bank list
    assert loans["hdfc-bank-loan-statement"]["name"] == "HDFC Bank"


def test_loan_statement_query():
    (q,) = gfetch.build_queries(["hdfc-bank-loan-statement"], [], date(2026, 11, 1), date(2026, 11, 30))
    assert q["label"] == "HDFC Bank · loan" and q["doc_type"] == "loan_statement"
    assert "has:attachment" in q["query"] and "filename:pdf" in q["query"] and '"loan statement"' in q["query"]


def test_extract_prefers_plain_and_strips_html():
    m = make_msg("x", "s", "a", datetime(2026, 1, 1), body_html="<style>.a{}</style><p>Total <b>&#8377;450</b></p>")
    text, atts = gfetch.extract(m["payload"])
    assert text == "Total ₹450" and atts == []


@pytest.mark.parametrize(
    ("subject", "body", "expected"),
    [
        ("Alert", "Rs.450.00 has been debited from account **1234 to VPA swiggy.food@icici on 12-11-26.",
         ("withdrawal", 45_000, date(2026, 11, 12), "Swiggy Food", "1234")),
        ("Transaction alert", "INR 1,299.00 spent on HDFC Bank Card XX5678 at AMAZON PAY on 2026-11-12 10:41:02.",
         ("withdrawal", 129_900, date(2026, 11, 12), "Amazon Pay", "5678")),
        ("Credit", "Your A/c XX1234 is credited with INR 80,000.00 on 01-Nov-26 by NEFT from ACME CORP. Avl Bal INR 1,20,000.",
         ("deposit", 8_000_000, date(2026, 11, 1), "Acme Corp", "1234")),
        ("x", "Your Credit Card XX9012 has been used for a transaction of INR 2,450.50 on Nov 10, 2026 at ZOMATO.",
         ("withdrawal", 245_050, date(2026, 11, 10), "Zomato", "9012")),
        ("x", "Rs 5,000 withdrawn from ATM using card ending 1111 on 03-11-2026.",
         ("withdrawal", 500_000, date(2026, 11, 3), "ATM", "1111")),
        ("Refund", "Rs 199 refund credited to your card ending 4321 from NETFLIX on 05/11/2026.",
         ("deposit", 19_900, date(2026, 11, 5), "Netflix", "4321")),
    ],
)
def test_parse_alert(subject, body, expected):
    s = parse_alert(subject, body, datetime(2026, 11, 13, 10))
    assert (s.type, s.amount, s.date, s.merchant, s.account_last4) == expected


def test_parse_alert_ignores_other_emails():
    assert parse_alert("Your statement", "Please find attached your account statement for October 2026.", None) is None
    assert parse_alert("Offer", "Get Rs.500 off on your next order!", None) is None  # no debit/credit word
    assert parse_alert("Debited", "Your account was debited.", None) is None  # no amount
    # no date in the text -> the email's date
    s = parse_alert("Alert", "Rs 100 debited from A/c XX1234 at CAFE", datetime(2026, 10, 2, 9))
    assert s.date == date(2026, 10, 2)


# ---------------------------------------------------------------- oauth flow + secrets


def test_connect_callback_and_paste_flow(client, connected, fake):
    token_call = connected[-1][1]
    assert token_call["grant_type"] == "authorization_code" and token_call["code_verifier"]
    assert token_call["client_secret"] == "s3cret"  # decrypted for the call
    st = client.get("/api/gmail/status").json()
    assert st["connected"] and st["email"] == "me@example.com"
    # wrong state is refused
    client.post("/api/guide", json={"action": "setup_done"})  # outside the setup page: back to Settings
    client.post("/api/gmail/disconnect")
    r = client.post("/api/gmail/connect", json={"origin": "http://localhost:9009"}).json()
    q = parse_qs(urlparse(r["url"]).query)
    assert q["scope"] == [gclient.SCOPE] and q["code_challenge_method"] == ["S256"] and r["direct"] is True
    bad = client.get("/api/gmail/callback", params={"code": "c", "state": "nope"}, follow_redirects=False)
    assert bad.status_code == 302 and "gmail=error" in bad.headers["location"]
    ok = client.get("/api/gmail/callback", params={"code": "c", "state": q["state"][0]}, follow_redirects=False)
    assert ok.headers["location"] == "/settings?gmail=connected"
    # paste flow (browser on another device)
    client.post("/api/gmail/disconnect")
    r2 = client.post("/api/gmail/connect", json={"origin": "http://moneymap.home.lan:9009"}).json()
    state2 = parse_qs(urlparse(r2["url"]).query)["state"][0]
    pasted = f"http://127.0.0.1:9009/api/gmail/callback?state={state2}&code=xyz&scope={gclient.SCOPE}"
    assert client.post("/api/gmail/callback-url", json={"url": pasted}).json()["connected"] is True
    assert client.post("/api/gmail/callback-url", json={"url": "http://x/?nothing=1"}).status_code == 422


def test_secrets_are_encrypted_at_rest(client, connected):
    db = sqlite3.connect(get_settings().data_dir / "users" / "1" / "moneymap.db")
    raw = " ".join(str(v) for v in db.execute("SELECT * FROM gmail_account").fetchone())
    raw += " ".join(str(v) for v in db.execute("SELECT * FROM gmail_mailbox").fetchone())
    db.close()
    assert "123-abc" in raw  # the client id isn't secret
    assert "s3cret" not in raw and "at-SECRET" not in raw and "rt-SECRET" not in raw


def test_changing_client_drops_token(client, connected, fake):
    other = json.dumps({"installed": {"client_id": "999-other", "client_secret": "x"}})
    st = client.put("/api/gmail/client", json={"json_text": other}).json()
    assert st["client_configured"] and not st["connected"]
    assert client.delete("/api/gmail/client").json()["client_configured"] is False


# ---------------------------------------------------------------- estimate + fetch


def estimate(client, **kw):
    body = {"template_ids": ["hdfc-bank-account-statement", "hdfc-bank-transaction-alerts"], "custom": ["from:swiggy.in"],
            "date_from": "2026-11-01", "date_to": "2026-11-30", **kw}
    r = client.post("/api/gmail/estimate", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def fetched(client):
    est = estimate(client)
    client.post(f"/api/gmail/runs/{est['id']}/start", json={})


def test_estimate_fetch_dedupe_and_inbox(client, connected, fake):
    est = estimate(client)
    assert est["matched_count"] == 4 and est["new_count"] == 4 and est["bytes_estimated"] == 200_000
    assert fake.full_gets == []  # estimate downloads nothing
    run = client.post(f"/api/gmail/runs/{est['id']}/start", json={}).json()
    run = client.get(f"/api/gmail/runs/{run['id']}").json()
    assert run["status"] == "done" and run["message_count"] == 4 and run["attachment_count"] == 2
    assert len(list(gfetch.attachments_dir().glob("*.pdf"))) == 1  # identical PDFs stored once
    again = estimate(client)
    assert again["matched_count"] == 4 and again["new_count"] == 0
    assert client.post(f"/api/gmail/runs/{est['id']}/start", json={}).status_code == 422  # can't replay
    assert client.get("/api/gmail/status").json()["last_fetch_to"] == "2026-11-30"
    assert [r["id"] for r in client.get("/api/gmail/runs").json()] == [run["id"]]

    page = client.get("/api/inbox").json()
    assert page["total"] == 4 and page["counts"] == {"new": 4, "handled": 0, "ignored": 0}
    by_id = {i["id"]: i for i in page["items"]}
    assert by_id["m4"]["doc_type"] == "transaction_alert" and by_id["m4"]["is_alert"] is True
    assert by_id["m1"]["doc_type"] == "bank_statement" and by_id["m1"]["is_alert"] is False
    swiggy = client.get("/api/inbox/m2").json()
    assert swiggy["body_text"].startswith("Order total ₹450") and swiggy["snippet"] == "Swiggy order delivered & more"
    assert client.get("/api/inbox", params={"q": "swiggy"}).json()["total"] == 1


def test_consent_required_over_threshold(client, connected, fake, monkeypatch):
    monkeypatch.setattr(gfetch, "consent_threshold", lambda: 0)  # anything > 0 bytes needs consent
    est = estimate(client)
    assert est["consent_required"] is True
    refused = client.post(f"/api/gmail/runs/{est['id']}/start", json={})
    assert refused.status_code == 422 and "Tick the confirmation" in refused.json()["detail"]
    assert client.post(f"/api/gmail/runs/{est['id']}/start", json={"consent": True}).status_code == 200


def test_fetch_error_keeps_progress(client, connected, fake):
    est = estimate(client)
    real = fake.get_message

    def flaky(mid, fmt="full"):
        if fmt == "full" and fake.full_gets:  # the first full download works, the next one fails
            raise RuntimeError("network down")
        return real(mid, fmt)

    fake.get_message = flaky
    run = client.post(f"/api/gmail/runs/{est['id']}/start", json={}).json()
    run = client.get(f"/api/gmail/runs/{run['id']}").json()
    assert run["status"] == "error" and "network down" in run["error"]
    assert client.get("/api/inbox").json()["total"] == 1  # the first email was kept
    fake.get_message = real
    assert estimate(client)["new_count"] == 3


def test_not_connected_errors(client, fake, monkeypatch):
    monkeypatch.setattr(gclient, "api_for", gclient.GmailAPI)  # the real one
    client.put("/api/gmail/client", json={"json_text": CLIENT_JSON})
    r = client.post("/api/gmail/estimate", json={"template_ids": ["hdfc-bank-account-statement"],
                                                 "date_from": "2026-11-01", "date_to": "2026-11-30"})
    assert r.status_code == 422 and "isn't connected" in r.json()["detail"]


def test_gmail_and_inbox_need_login(anon):
    assert anon.get("/api/gmail/status").status_code == 401
    assert anon.get("/api/inbox").status_code == 401


# ---------------------------------------------------------------- inbox ↔ transactions


def test_alert_email_suggestion_matches_account(client, connected, fake):
    hdfc = client.post("/api/accounts", json={"name": "HDFC Savings", "type": "asset", "account_number": "50100 1234"}).json()
    client.post("/api/accounts", json={"name": "Wallet", "type": "cash"})
    fetched(client)
    s = client.get("/api/inbox/m4").json()["suggestion"]
    assert s == {"type": "withdrawal", "amount": 45_000, "date": "2026-11-12", "merchant": "Swiggy",
                 "account_last4": "1234", "account_id": hdfc["id"], "category_id": None, "payee": None, "rule": None}
    assert client.get("/api/inbox/m1").json()["suggestion"] is None  # statement email: for statement import


def test_create_transaction_from_email(client, connected, fake, bank):
    fetched(client)
    t = spend(client, bank, 45_000, desc="Swiggy order", payee="Swiggy", gmail_message_id="m2")
    assert t["gmail"] == {"id": "m2", "subject": "Swiggy order delivered", "from_addr": "Swiggy <noreply@swiggy.in>"}
    assert client.get("/api/inbox/counts").json()["handled"] == 1
    detail = client.get("/api/inbox/m2").json()
    assert detail["status"] == "handled" and [x["id"] for x in detail["transactions"]] == [t["id"]]
    t2 = spend(client, bank, 1_000, desc="Tip", payee="Swiggy", gmail_message_id="m2")
    client.delete(f"/api/transactions/{t['id']}")
    assert client.get("/api/inbox/m2").json()["status"] == "handled"
    client.delete(f"/api/transactions/{t2['id']}")
    assert client.get("/api/inbox/m2").json()["status"] == "new"
    bad = client.post("/api/transactions", json={"type": "withdrawal", "date": "2026-11-05", "amount": 1,
                                                 "description": "x", "source_id": bank["id"],
                                                 "destination_name": "y", "gmail_message_id": "missing"})
    assert bad.status_code == 422


def test_ignore_restore_and_attachment_download(client, connected, fake):
    fetched(client)
    assert client.patch("/api/inbox/m1", json={"status": "ignored"}).json()["status"] == "ignored"
    assert client.get("/api/inbox", params={"status": "ignored"}).json()["total"] == 1
    assert client.patch("/api/inbox/m1", json={"status": "new"}).json()["status"] == "new"
    att = client.get("/api/inbox/m1").json()["attachments"][0]
    r = client.get(f"/api/inbox/m1/attachments/{att['id']}")
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-disposition"].startswith("inline")
    assert "content-security-policy" not in r.headers  # Chrome's PDF viewer refuses sandboxed PDFs
    assert client.get(f"/api/inbox/m1/attachments/{att['id']}", params={"download": True}).headers[
        "content-disposition"].startswith("attachment")
    assert client.get(f"/api/inbox/m2/attachments/{att['id']}").status_code == 404  # wrong message


# ---------------------------------------------------------------- reset


def test_reset_data_keeps_gmail_and_reopens_emails(client, connected, fake, bank):
    fetched(client)
    spend(client, bank, 45_000, gmail_message_id="m4")
    assert client.get("/api/inbox/m4").json()["status"] == "handled"
    r = client.post("/api/reset", json={"mode": "data", "password": "test-password", "confirm": "RESET", "backup": False})
    assert r.status_code == 200
    assert client.get("/api/gmail/status").json()["connected"] is True
    assert client.get("/api/inbox/m4").json()["status"] == "new"
    assert len(list(gfetch.attachments_dir().glob("*.pdf"))) == 1


def test_reset_everything_removes_gmail(client, connected, fake, monkeypatch):
    fetched(client)
    monkeypatch.setattr(gclient.httpx, "post", lambda *a, **k: None)  # don't call Google to revoke
    r = client.post("/api/reset", json={"mode": "everything", "password": "test-password", "confirm": "RESET",
                                        "backup": False})
    assert r.status_code == 200
    client.post("/api/auth/setup", json={"username": "new", "password": "another-pass"})
    st = client.get("/api/gmail/status").json()
    assert st["client_configured"] is False and st["connected"] is False
    assert client.get("/api/inbox").json()["total"] == 0
    assert list(gfetch.attachments_dir().glob("*")) == []


def test_pick_which_emails_to_fetch(client, connected, fake):
    est = estimate(client)
    found = {f["id"]: f for f in est["found"]}
    assert set(found) == {"m1", "m2", "m3", "m4"} and not any(f["known"] for f in found.values())
    m1 = found["m1"]
    assert m1["subject"] == "Your HDFC Bank statement" and "hdfcbank" in m1["from"] and m1["size"] == 50_000
    assert m1["date"].startswith("2026-11-02") and est["queries"][m1["q"]]["label"]
    assert fake.full_gets == []  # still nothing downloaded
    # nothing ticked is refused; then fetch only two
    assert client.post(f"/api/gmail/runs/{est['id']}/start", json={"ids": []}).status_code == 422
    run = client.post(f"/api/gmail/runs/{est['id']}/start", json={"ids": ["m1", "m2"]}).json()
    run = client.get(f"/api/gmail/runs/{run['id']}").json()
    assert run["status"] == "done" and run["message_count"] == 2 and run["bytes_estimated"] == 100_000
    assert sorted(fake.full_gets) == ["m1", "m2"]
    # the next search lists them as already in the Inbox
    again = {f["id"]: f["known"] for f in estimate(client)["found"]}
    assert again == {"m1": True, "m2": True, "m3": False, "m4": False}


def test_found_emails_show_which_account(client, connected, fake):
    """The last 4 digits in a subject or preview, matched to your account / card."""
    client.post("/api/accounts", json={"name": "HDFC Savings", "type": "asset", "account_number": "50100012345678"})
    fake.messages["m1"]["payload"]["headers"][1]["value"] = "Statement for A/c XX5678 — November"
    fake.messages["m3"]["snippet"] = "Your card ending 9999 statement is ready"
    found = {f["id"]: f for f in estimate(client)["found"]}
    assert (found["m1"]["last4"], found["m1"]["account"]) == ("5678", "HDFC Savings")
    assert (found["m3"]["last4"], found["m3"]["account"]) == ("9999", None)  # no account with those digits
    assert found["m2"]["last4"] is None

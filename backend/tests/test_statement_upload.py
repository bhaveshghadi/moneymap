"""Uploading a statement PDF directly (downloaded from the bank's website)."""
import base64

from app.config import get_settings

from .test_statement_import import ICICI_LINES, PASSWORD, icici, make_pdf  # noqa: F401 (fixture)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_upload_password_account_and_same_file(client, icici):  # noqa: F811
    pdf = b64(make_pdf(ICICI_LINES))
    body = {"filename": "OpTransactionHistory.pdf", "content_b64": pdf}
    r = client.post("/api/statements/upload", json=body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "password_required"
    assert list((get_settings().data_dir / "uploads").glob("*.pdf")) == []  # nothing kept until it opens
    r = client.post("/api/statements/upload", json={**body, "password": "nope"})
    assert r.json()["detail"]["code"] == "wrong_password"

    r = client.post("/api/statements/upload", json={**body, "password": PASSWORD})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["filename"] == "OpTransactionHistory.pdf" and d["upload_path"] and d["gmail_message_id"] is None
    assert d["account_id"] == icici["acct"]["id"] and d["account_suggested"] is True  # from …2840 on the statement
    assert len(d["rows"]) == 6
    # the same file again opens the same draft, no password needed
    assert client.post("/api/statements/upload", json=body).json()["id"] == d["id"]
    # re-reading the PDF works for uploads too
    r = client.post(f"/api/statements/{d['id']}/reread-pdf", json={"password": PASSWORD})
    assert r.status_code == 200 and len(r.json()["rows"]) == 6
    # discarding removes the uploaded file
    assert client.delete(f"/api/statements/{d['id']}").status_code == 204
    assert list((get_settings().data_dir / "uploads").glob("*.pdf")) == []


def test_upload_chosen_account_and_remembered_password(client, icici):  # noqa: F811
    card = icici["card"]["id"]
    r = client.post("/api/statements/upload", json={"filename": "a.pdf", "content_b64": b64(make_pdf(ICICI_LINES)),
                                                    "account_id": card, "password": PASSWORD, "remember_password": True})
    assert r.status_code == 201 and r.json()["account_id"] == card and r.json()["account_suggested"] is False
    # another statement for the same account opens with the remembered password
    r = client.post("/api/statements/upload", json={"filename": "b.pdf", "content_b64": b64(make_pdf(ICICI_LINES[:5])),
                                                    "account_id": card})
    assert r.status_code == 201, r.text


def test_upload_rejects_non_pdf_and_bad_account(client, icici):  # noqa: F811
    r = client.post("/api/statements/upload", json={"filename": "x.csv", "content_b64": b64(b"date,amount\n")})
    assert r.json()["detail"]["code"] == "not_pdf"
    r = client.post("/api/statements/upload", json={"filename": "x.pdf", "content_b64": "%%%not base64"})
    assert r.json()["detail"]["code"] == "bad_file"
    payee = client.post("/api/accounts", json={"name": "Some shop", "type": "expense"}).json()
    r = client.post("/api/statements/upload", json={"filename": "x.pdf", "content_b64": b64(make_pdf(ICICI_LINES, None)),
                                                    "account_id": payee["id"]})
    assert r.json()["detail"]["code"] == "bad_account"
    r = client.post("/api/statements/upload", json={"filename": "x.pdf", "content_b64": b64(make_pdf(ICICI_LINES, None))})
    assert r.status_code == 201  # unprotected PDFs need no password


def test_upload_of_a_pdf_already_fetched_from_gmail(client, icici):  # noqa: F811
    # the Inbox copy (fixture) — give it its real hash, as the Gmail fetch does
    import hashlib

    from app.db import SessionLocal
    from app.models import GmailAttachment
    from app.modules.gmail.fetch import attachments_dir
    with SessionLocal() as db:
        att = db.get(GmailAttachment, icici["att"])
        data = (attachments_dir() / att.path).read_bytes()
        att.sha256 = hashlib.sha256(data).hexdigest()
        db.commit()
    body = {"filename": "downloaded.pdf", "content_b64": b64(data), "password": PASSWORD}
    # not opened from the Inbox yet → the upload opens it as the email's statement
    r = client.post("/api/statements/upload", json=body).json()
    assert r["gmail_message_id"] == "stmt1" and r["upload_path"] is None and r["opened_existing"] is False
    assert not (get_settings().data_dir / "uploads" / f"{att.sha256[:16]}.pdf").exists()  # no second copy kept
    # uploading it again → the same statement, flagged as already open
    again = client.post("/api/statements/upload", json=body).json()
    assert again["id"] == r["id"] and again["opened_existing"] is True
    assert len(client.get("/api/statements").json()) == 1


def test_same_statement_different_file_is_flagged(client, icici):  # noqa: F811
    first = client.post("/api/statements", json={"attachment_id": icici["att"], "password": PASSWORD}).json()
    # e.g. downloaded from the bank's website: different file, same transactions
    other = client.post("/api/statements/upload", json={"filename": "web.pdf", "content_b64": b64(make_pdf(ICICI_LINES, None))}).json()
    assert other["id"] != first["id"]
    assert [(o["id"], o["source"], o["shared_rows"]) for o in other["overlaps"]] == [(first["id"], "email", 6)]
    assert client.get(f"/api/statements/{first['id']}").json()["overlaps"][0]["source"] == "upload"
    # an unrelated statement isn't flagged
    lone = client.post("/api/statements/upload", json={"filename": "x.pdf", "content_b64": b64(make_pdf(
        ["Savings A/c XXXXXXXX2840", "01-12-2026 B/F 1,000.00", "02-12-2026 UPI/A/a@ybl/x/ICICI 10.00 990.00",
         "03-12-2026 UPI/B/b@ybl/x/ICICI 20.00 970.00", "04-12-2026 UPI/C/c@ybl/x/ICICI 30.00 940.00"], None))}).json()
    assert lone["overlaps"] == []

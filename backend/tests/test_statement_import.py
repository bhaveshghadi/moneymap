"""Statement import: unlock → parse → review (history, duplicates) → import."""
import io
from datetime import datetime

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.db import SessionLocal
from app.models import GmailAttachment, GmailMessage
from app.modules.gmail.fetch import attachments_dir

from .helpers import spend

PASSWORD = "test-pdf-pass"

# ICICI savings e-statement layout (balance column → direction from balance delta)
ICICI_LINES = [
    "ICICI BANK STATEMENT",
    "Savings A/c XXXXXXXX2840",
    "DATE MODE PARTICULARS DEPOSITS WITHDRAWALS BALANCE",
    "01-11-2026 B/F 50,000.00",
    "02-11-2026 UPI/SWIGGY/swiggy@ybl/food/ICICI 450.00 49,550.00",
    "03-11-2026 UPI/ZEPTO/zepto@ybl/grocery/ICICI 820.00 48,730.00",
    "04-11-2026 UPI/RAMESH KUMAR/9876543210@ybl/rent/SBI 15,000.00 33,730.00",
    "05-11-2026 NEFT CR ACME TECH SALARY NOV 90,000.00 1,23,730.00",
    "06-11-2026 BIL/ICICI CC PAYMENT 4375XXXX9012 12,000.00 1,11,730.00",
    "07-11-2026 UPI/DMART/dmart@icici/shopping/ICICI 2,100.00 1,09,630.00",
    "30-11-2026 CLOSING BALANCE 1,09,630.00",
]


def make_pdf(lines: list[str], password: str | None = PASSWORD) -> bytes:
    """A real text PDF (Helvetica, one line per row), optionally encrypted."""
    w = PdfWriter()
    page = w.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    ops = ["BT", "/F1 9 Tf", "40 760 Td"]
    for line in lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops += [f"({safe}) Tj", "0 -14 Td"]
    ops.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(ops).encode("latin-1"))
    page[NameObject("/Contents")] = w._add_object(stream)
    if password:
        w.encrypt(password, algorithm="AES-256")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def add_email(lines, mid="stmt1", sender="Estatement <estatement@icici.bank.in>", password=PASSWORD) -> int:
    data = make_pdf(lines, password)
    name = f"{mid}.pdf"
    (attachments_dir() / name).write_bytes(data)
    with SessionLocal() as db:
        m = GmailMessage(id=mid, from_addr=sender, subject="ICICI Bank Statement", sent_at=datetime(2026, 12, 2),
                         status="new")
        m.attachments.append(GmailAttachment(filename="Statement.pdf", mime_type="application/pdf", size=len(data),
                                             sha256=mid, path=name))
        db.add(m)
        db.commit()
        return m.attachments[0].id


def cat(client, name):
    return next(c["id"] for c in client.get("/api/categories").json() if c["name"] == name)


@pytest.fixture()
def icici(client):
    acct = client.post("/api/accounts", json={"name": "ICICI Savings", "type": "asset", "account_number": "XXXX2840",
                                              "opening_balance": 5_000_000}).json()
    # the other side of transfers (cards come later as their own feature)
    card = client.post("/api/accounts", json={"name": "Wallet", "type": "cash"}).json()
    return {"acct": acct, "card": card, "att": add_email(ICICI_LINES)}


def rows_by_payee(detail):
    return {r["payee"]: r for r in detail["rows"]}


def test_password_flow(client, icici):
    r = client.post("/api/statements", json={"attachment_id": icici["att"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "password_required"
    r = client.post("/api/statements", json={"attachment_id": icici["att"], "password": "nope"})
    assert r.json()["detail"]["code"] == "wrong_password"
    r = client.post("/api/statements", json={"attachment_id": icici["att"], "password": PASSWORD, "remember_password": True})
    assert r.status_code == 201
    # same PDF again → same import, no password needed
    again = client.post("/api/statements", json={"attachment_id": icici["att"]})
    assert again.json()["id"] == r.json()["id"]
    # a second statement from the same sender uses the remembered password
    att2 = add_email(ICICI_LINES[:5], mid="stmt2")
    assert client.post("/api/statements", json={"attachment_id": att2}).status_code == 201


def test_review_suggestions_duplicates_and_import(client, icici):
    acct, card = icici["acct"], icici["card"]
    dining, groceries, housing, shopping = (cat(client, n) for n in
                                            ("Dining", "Groceries", "Rent", "Shopping"))
    # history: you categorised Swiggy before
    spend(client, acct, 30_000, desc="old order", payee="Swiggy", date="2026-10-10", category_id=dining)
    # already in Ledger: the DMart spend (recorded by hand a day later)
    spend(client, acct, 210_000, desc="DMart groceries", payee="DMart", date="2026-11-08")

    d = client.post("/api/statements", json={"attachment_id": icici["att"], "password": PASSWORD}).json()
    assert d["account_id"] == acct["id"] and d["account_suggested"] and d["account_last4"] == "2840"
    assert len(d["rows"]) == 6 and any("CLOSING BALANCE" in u for u in d["unparsed"])
    rows = rows_by_payee(d)
    assert rows["Swiggy"]["status"] == "ready" and rows["Swiggy"]["category_id"] == dining
    assert rows["Swiggy"]["suggestion"].startswith("Like 1 past")
    assert rows["Zepto"]["status"] == "needs_category" and rows["Zepto"]["suggestion"] is None  # no history
    assert rows["Dmart"]["status"] == "duplicate" and rows["Dmart"]["include"] is False
    assert rows["Ramesh Kumar"]["status"] == "needs_category" and rows["Ramesh Kumar"]["amount"] == -1_500_000
    salary = next(r for r in d["rows"] if "SALARY" in r["description"])
    assert salary["kind"] == "income" and salary["amount"] == 9_000_000 and salary["status"] == "needs_category"
    ccpay = next(r for r in d["rows"] if "CC PAYMENT" in r["description"])
    assert ccpay["kind"] == "transfer" and ccpay["status"] == "needs_account"

    # import is blocked until everything new is resolved
    r = client.post(f"/api/statements/{d['id']}/import")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unresolved"

    base = f"/api/statements/{d['id']}/rows"
    client.patch(f"{base}/{rows['Ramesh Kumar']['id']}", json={"category_id": housing})
    client.patch(f"{base}/{salary['id']}", json={"leave_uncategorised": True})
    assert client.patch(f"{base}/{ccpay['id']}", json={"transfer_account_id": acct["id"]}).status_code == 422  # same account
    client.patch(f"{base}/{ccpay['id']}", json={"transfer_account_id": card["id"]})
    # your choice for Zepto must survive the import
    client.patch(f"{base}/{rows['Zepto']['id']}", json={"category_id": shopping})
    bad = client.patch(f"{base}/{rows['Swiggy']['id']}", json={"kind": "income"})
    assert bad.status_code == 422  # money out can't be income

    res = client.post(f"/api/statements/{d['id']}/import").json()
    assert res["imported"] == 5
    assert res["statement"]["status"] == "imported" and res["statement"]["counts"]["imported"] == 5

    txns = {t["description"]: t for t in client.get("/api/transactions", params={"limit": 50}).json()["items"]}
    assert txns["UPI/SWIGGY/swiggy@ybl/food/ICICI"]["category"]["id"] == dining
    assert txns["UPI/ZEPTO/zepto@ybl/grocery/ICICI"]["category"]["id"] == shopping
    rk = txns["UPI/RAMESH KUMAR/9876543210@ybl/rent/SBI"]
    assert rk["destination"]["name"] == "Ramesh Kumar" and rk["gmail"]["id"] == "stmt1"
    cc = txns["BIL/ICICI CC PAYMENT 4375XXXX9012"]
    assert cc["type"] == "transfer" and cc["destination"]["id"] == card["id"]
    sal = next(t for k, t in txns.items() if "SALARY" in k)
    assert sal["type"] == "deposit" and sal["category"] is None
    balances = {a["name"]: a["balance"] for a in client.get("/api/accounts").json()}
    assert balances["ICICI Savings"] == 5_000_000 - 30_000 - 210_000 - 45_000 - 82_000 - 1_500_000 + 9_000_000 - 1_200_000
    assert balances["Wallet"] == 1_200_000
    assert client.get("/api/inbox/stmt1").json()["status"] == "handled"

    # the next statement: Ramesh is recognised from history now
    att2 = add_email(["ICICI BANK STATEMENT", "Savings A/c XXXXXXXX2840",
                      "01-12-2026 B/F 1,09,630.00",
                      "04-12-2026 UPI/RAMESH KUMAR/9876543210@ybl/rent/SBI 15,000.00 94,630.00"], mid="stmt3")
    d2 = client.post("/api/statements", json={"attachment_id": att2, "password": PASSWORD}).json()
    r2 = d2["rows"][0]
    assert r2["status"] == "ready" and r2["category_id"] == housing and r2["suggestion"].startswith("Like 1 past")


def test_account_choice_and_discard(client, icici):
    other = client.post("/api/accounts", json={"name": "Pocket money", "type": "cash"}).json()
    d = client.post("/api/statements", json={"attachment_id": icici["att"], "password": PASSWORD}).json()
    assert client.patch(f"/api/statements/{d['id']}", json={"account_id": icici["card"]["id"] + 999}).status_code == 422
    d = client.patch(f"/api/statements/{d['id']}", json={"account_id": other["id"]}).json()
    assert d["account_id"] == other["id"]
    d = client.patch(f"/api/statements/{d['id']}", json={"account_id": None}).json()
    assert client.post(f"/api/statements/{d['id']}/import").json()["detail"]["code"] == "needs_account"
    assert client.delete(f"/api/statements/{d['id']}").status_code == 204
    assert client.get("/api/statements").json() == []


def test_unencrypted_and_non_pdf(client):
    att = add_email(["Amazon Pay ICICI Bank Credit Card Statement", "4375XXXXXXXX9012",
                     "02/11/2026 AMAZON PAY INDIA 1,299.00", "05/11/2026 PAYMENT RECEIVED THANK YOU 5,000.00 CR"],
                    mid="card1", password=None)
    d = client.post("/api/statements", json={"attachment_id": att}).json()
    assert d["doc_type"] == "card_statement" and d["account_last4"] == "9012" and d["account_id"] is None
    amounts = sorted(r["amount"] for r in d["rows"])
    assert amounts == [-129_900, 500_000]
    pay = next(r for r in d["rows"] if r["amount"] > 0)
    assert pay["kind"] == "transfer"
    with SessionLocal() as db:
        m = GmailMessage(id="x1", from_addr="a@b.c", subject="s", status="new")
        m.attachments.append(GmailAttachment(filename="a.csv", mime_type="text/csv", size=1, sha256="x", path="a.csv"))
        db.add(m)
        db.commit()
        aid = m.attachments[0].id
    assert client.post("/api/statements", json={"attachment_id": aid}).json()["detail"]["code"] == "not_pdf"


def test_unreadable_layout_is_kept_and_can_be_reread(client, monkeypatch):
    """A PDF whose rows the parser can't find is still saved (with its text),
    and 'reparse' re-reads it later without the password."""
    client.post("/api/accounts", json={"name": "ICICI Savings", "type": "asset", "account_number": "XXXX2840"})
    att = add_email(["ICICI BANK STATEMENT", "Savings A/c XXXXXXXX2840", "Nov 02 2026  SWIGGY  450.00"], mid="odd1")
    d = client.post("/api/statements", json={"attachment_id": att, "password": PASSWORD}).json()
    assert d["rows"] == [] and any("SWIGGY" in u for u in d["unparsed"])
    # pretend the parser learned this layout: re-read uses the saved text, no password
    import app.modules.statements.router as routes
    from app.modules.statements.parser import ParsedStatement, ParsedTxn

    def fake_parse(text, doc_type="bank_statement", opening_balance=None):
        return ParsedStatement("bank_statement", "2840",
                               [ParsedTxn("2026-11-02", -45_000, "SWIGGY", "Nov 02 2026  SWIGGY  450.00")], [])

    monkeypatch.setattr(routes, "parse_statement", fake_parse)
    d = client.post(f"/api/statements/{d['id']}/reparse").json()
    assert len(d["rows"]) == 1 and d["rows"][0]["payee"] == "Swiggy" and d["account_id"] is not None


from pdfminer.fontmetrics import FONT_METRICS  # noqa: E402

HELV = FONT_METRICS["Helvetica"][1]


def make_glyph_pdf(rows: list[list[tuple[float, str]]], password: str | None = None) -> bytes:
    """Like ICICI e-statements: every character drawn on its own at an explicit
    position; each row is a list of (x, text) column cells."""
    w = PdfWriter()
    page = w.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    ops = ["BT", "/F1 8 Tf"]
    y = 760
    for row in rows:
        for x, cell in row:
            cx = x
            for ch in cell:
                if ch != " ":
                    safe = ch.replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")
                    ops += [f"1 0 0 1 {cx:.2f} {y} Tm", f"({safe}) Tj"]
                cx += HELV.get(ch, 556) * 8 / 1000  # real Helvetica advance widths
        y -= 13
    ops.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(ops).encode("latin-1"))
    page[NameObject("/Contents")] = w._add_object(stream)
    if password:
        w.encrypt(password, algorithm="AES-256")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()



def text_to_glyph_rows(text: str) -> list[list[tuple[float, str]]]:
    """Lay out 'cell   cell   cell' lines as positioned columns."""
    rows = []
    for line in text.strip().splitlines():
        x, cells = 30.0, []
        for cell in line.split("   "):
            cells.append((x, cell))
            x += sum(HELV.get(ch, 556) for ch in cell) * 8 / 1000 + 18
        rows.append(cells)
    return rows

def test_per_glyph_pdf_is_read_as_words(tmp_path):
    from app.modules.statements.extract import extract_text

    rows = [
        [(40, "DATE"), (110, "MODE"), (170, "PARTICULARS"), (420, "DEPOSITS"), (480, "WITHDRAWALS"), (550, "BALANCE")],
        [(40, "01-09-2026"), (170, "B/F"), (550, "1,22,950.91")],
        [(170, "SUNRISE STORES")],
        [(40, "01-09-2026"), (170, "UPI/SUNRISEST/sunrise01@idf/UPI/IDFC"), (480, "120.00"), (550, "1,22,830.91")],
    ]
    p = tmp_path / "g.pdf"
    p.write_bytes(make_glyph_pdf(rows))
    text = extract_text(p)
    assert "01-09-2026" in text and "1,22,830.91" in text and "SUNRISE STORES" in text
    assert "UPI/SUNRISEST/sunrise01@idf/UPI/IDFC" in text



def test_icici_glyph_pdf_end_to_end(client):
    """A password-protected, glyph-by-glyph ICICI statement imports cleanly,
    and 'reread-pdf' rebuilds a draft from the PDF."""
    from .test_statement_parser import ICICI_SAVINGS

    client.post("/api/accounts", json={"name": "ICICI Savings", "type": "asset", "account_number": "XXXX5678",
                                       "opening_balance": 12_295_091})
    data = make_glyph_pdf(text_to_glyph_rows(ICICI_SAVINGS), PASSWORD)
    (attachments_dir() / "glyph.pdf").write_bytes(data)
    with SessionLocal() as db:
        m = GmailMessage(id="g1", from_addr="Estatement <estatement@icici.bank.in>", subject="ICICI", status="new")
        m.attachments.append(GmailAttachment(filename="Statement_2026MTH09.pdf", mime_type="application/pdf",
                                             size=len(data), sha256="g", path="glyph.pdf"))
        db.add(m)
        db.commit()
        att = m.attachments[0].id
    d = client.post("/api/statements", json={"attachment_id": att, "password": PASSWORD}).json()
    assert d["account_last4"] == "5678" and d["account_id"] is not None
    assert len(d["rows"]) == 12, [r["raw"] for r in d["rows"]]
    rows = {r["amount"]: r for r in d["rows"]}
    assert rows[-12_000]["payee"] == "Sunrise Stores" and rows[-19_900]["payee"] == "Netflix Com"
    assert rows[34_800]["kind"] == "income"
    # simulate a draft read by the old extractor: garbled text, no rows; then re-read the PDF
    with SessionLocal() as db:
        from app.models import StatementImport
        imp = db.get(StatementImport, d["id"])
        imp.text = "0 1-09 -202 6 garbled"
        imp.rows = []
        db.commit()
    assert client.post(f"/api/statements/{d['id']}/reparse").json()["rows"] == []
    bad = client.post(f"/api/statements/{d['id']}/reread-pdf", json={"password": "nope"})
    assert bad.json()["detail"]["code"] == "wrong_password"
    again = client.post(f"/api/statements/{d['id']}/reread-pdf", json={"password": PASSWORD}).json()
    assert len(again["rows"]) == 12


def test_reparse_keeps_your_edits(client, icici):
    d = client.post("/api/statements", json={"attachment_id": icici["att"], "password": PASSWORD}).json()
    base = f"/api/statements/{d['id']}/rows"
    rows = sorted(d["rows"], key=lambda r: r["idx"])
    a, b, c = rows[0], rows[1], rows[2]
    gift = cat(client, "Gifts Given") if a["amount"] < 0 else cat(client, "Gift")
    client.patch(f"{base}/{a['id']}", json={"category_id": gift})
    client.patch(f"{base}/{b['id']}", json={"payee": "My own name", "include": False})
    again = client.post(f"/api/statements/{d['id']}/reparse").json()
    by_bal = {r["balance"]: r for r in again["rows"]}
    assert by_bal[a["balance"]]["category_id"] == gift and by_bal[a["balance"]]["status"] == "ready"
    assert by_bal[a["balance"]]["payee"] == a["payee"]  # auto payee re-derived, unchanged here
    assert by_bal[b["balance"]]["payee"] == "My own name" and by_bal[b["balance"]]["include"] is False
    assert by_bal[c["balance"]]["category_id"] == c["category_id"]  # untouched row recomputed as before


REPEAT_LINES = [
    "ICICI BANK STATEMENT",
    "Savings A/c XXXXXXXX2840",
    "DATE MODE PARTICULARS DEPOSITS WITHDRAWALS BALANCE",
    "01-11-2026 B/F 50,000.00",
    "02-11-2026 UPI/FOODAPP/foodapp@ybl/food/ICICI 450.00 49,550.00",
    "03-11-2026 UPI/FOODAPP/foodapp@ybl/food/ICICI 300.00 49,250.00",
    "04-11-2026 UPI/FOODAPP/foodapp@ybl/food/ICICI 200.00 49,050.00",
    "05-11-2026 UPI/FOODAPP/foodapp@ybl/food/ICICI 100.00 48,950.00",
    "06-11-2026 UPI/CORNERSHOP/corner@ybl/misc/ICICI 80.00 48,870.00",
]


def test_apply_category_to_same_payee_rows(client, icici):
    att = add_email(REPEAT_LINES, mid="rep1")
    d = client.post("/api/statements", json={"attachment_id": att, "password": PASSWORD}).json()
    base = f"/api/statements/{d['id']}/rows"
    rows = sorted(d["rows"], key=lambda r: r["idx"])
    food = [r for r in rows if r["payee"] == rows[0]["payee"]]
    assert len(food) == 4
    first, second = food[0], food[1]
    # nothing chosen yet on the source row → refused
    assert client.post(f"{base}/{first['id']}/apply-similar").status_code == 422
    dining, groceries = cat(client, "Dining"), cat(client, "Groceries")
    client.patch(f"{base}/{second['id']}", json={"category_id": groceries})  # your own choice: kept
    client.patch(f"{base}/{first['id']}", json={"category_id": dining})
    after = client.post(f"{base}/{first['id']}/apply-similar").json()
    by_id = {r["id"]: r for r in after["rows"]}
    assert [by_id[r["id"]]["category_id"] for r in food] == [dining, groceries, dining, dining]
    assert by_id[food[2]["id"]]["status"] == "ready"
    other = next(r for r in after["rows"] if r["payee"] != first["payee"])
    assert other["category_id"] is None  # different payee untouched



def test_cas_opens_in_investments(client):
    att = add_email(["Consolidated Account Statement", "CAMS", "Folio No: 12345678", "01-11-2026 Purchase 5,000.00"],
                    mid="cas1", password=None)
    r = client.post("/api/statements", json={"attachment_id": att})
    detail = r.json()["detail"]
    assert r.status_code == 422 and detail["code"] == "cas" and detail["cas_id"]
    # opening it again finds the same draft
    again = client.post("/api/statements", json={"attachment_id": att}).json()["detail"]
    assert again["cas_id"] == detail["cas_id"]
    assert client.get(f"/api/investments/cas/{detail['cas_id']}").status_code == 200


def test_remembered_password_is_encrypted(client, icici):
    import sqlite3

    from app.config import get_settings

    client.post("/api/statements", json={"attachment_id": icici["att"], "password": PASSWORD, "remember_password": True})
    db = sqlite3.connect(get_settings().data_dir / "moneymap.db")
    values = [v for (k, v) in db.execute("SELECT key, value FROM setting") if k.startswith("pdf_password:")]
    db.close()
    assert len(values) == 1 and PASSWORD not in values[0]


def test_statements_need_login(anon):
    assert anon.get("/api/statements").status_code == 401

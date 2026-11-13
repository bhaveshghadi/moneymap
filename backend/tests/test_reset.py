"""Settings → Reset: data only, or everything (factory reset)."""

from app.config import get_settings
from app.db import SessionLocal
from app.models import Setting

from .helpers import spend

PW = "test-password"


def _seed(client, bank):
    spend(client, bank, 50_000, payee="Cafe", tags=["trip"])
    client.post("/api/categories", json={"name": "My own", "kind": "expense"})
    client.post("/api/budgets", json={"name": "Food", "mode": "fixed", "amount": 100_000})
    with SessionLocal() as db:
        db.add(Setting(key="theme", value="dark"))
        db.commit()


def test_reset_needs_login(anon):
    assert anon.post("/api/reset", json={"mode": "data", "password": PW, "confirm": "RESET"}).status_code == 401


def test_reset_needs_password_and_confirm_word(client, bank):
    assert client.post("/api/reset", json={"mode": "data", "password": PW, "confirm": "yes"}).status_code == 422
    assert client.post("/api/reset", json={"mode": "data", "password": "nope", "confirm": "RESET"}).status_code == 400
    assert client.post("/api/reset", json={"mode": "all", "password": PW, "confirm": "RESET"}).status_code == 422
    assert len(client.get("/api/accounts").json()) == 1  # nothing deleted


def test_reset_data_keeps_login_and_settings(client, bank):
    _seed(client, bank)
    r = client.post("/api/reset", json={"mode": "data", "password": PW, "confirm": " RESET "}).json()
    assert r["signed_out"] is False and r["backup_file"].endswith("before-reset-data.db")
    assert (get_settings().data_dir / "backups" / r["backup_file"]).stat().st_size > 0
    assert client.get("/api/auth/status").json()["authenticated"] is True
    assert client.get("/api/accounts").json() == []
    assert client.get("/api/tags").json() == []
    assert client.get("/api/budgets").json()["budgets"] == []
    assert client.get("/api/transactions").json()["total"] == 0
    cats = client.get("/api/categories").json()
    assert len(cats) == 51 and "My own" not in {c["name"] for c in cats}  # starter list again
    with SessionLocal() as db:
        assert db.get(Setting, "theme").value == "dark"


def test_reset_everything_is_factory_reset(client, bank):
    _seed(client, bank)
    r = client.post("/api/reset", json={"mode": "everything", "password": PW, "confirm": "RESET", "backup": False})
    assert r.status_code == 200 and r.json() == {"mode": "everything", "backup_file": None, "signed_out": True}
    st = client.get("/api/auth/status").json()
    assert st["setup_required"] is True and st["authenticated"] is False
    with SessionLocal() as db:
        assert db.query(Setting).count() == 0
    # first-run setup works again and adds the starter categories
    assert client.post("/api/auth/setup", json={"username": "new", "password": "another-pass"}).status_code == 200
    assert len(client.get("/api/categories").json()) == 51
    assert client.get("/api/accounts").json() == []

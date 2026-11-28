"""Multi-user foundation: each person's data in their own file; logins in users.db; the one-time move
of single-user data. Made-up people and numbers."""

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent


def _add_person(username: str, password: str = "second-pass-123", **kw) -> int:
    from app.core.users import Login, users_session
    from app.modules.auth.security import hash_password
    from app.modules.auth.service import prepare_user_data

    with users_session() as db:
        u = Login(username=username, password_hash=hash_password(password), **kw)
        db.add(u)
        db.commit()
    prepare_user_data(u.id)
    return u.id


def _signed_in(username: str, password: str = "second-pass-123") -> TestClient:
    from app.main import app

    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c


def test_each_person_sees_only_their_own_data(client, bank):
    uid = _add_person("second")
    assert uid == 2
    other = _signed_in("second")
    assert other.get("/api/accounts").json() == []  # the admin's bank isn't there
    assert other.get(f"/api/accounts/{bank['id']}").status_code == 404
    mine = other.post("/api/accounts", json={"name": "Second's wallet", "type": "cash", "opening_balance": 500_00})
    assert mine.status_code == 201
    assert [a["name"] for a in client.get("/api/accounts").json()] == ["Bank"]
    assert len(other.get("/api/categories").json()) == 53  # a new person gets the starter categories
    st = other.get("/api/auth/status").json()
    assert st["username"] == "second" and st["is_admin"] is False
    from app.db import user_db_path

    assert user_db_path(2).exists() and user_db_path(1) != user_db_path(2)


def test_folders_are_per_person(client):
    from app.db import as_user, user_dir

    with as_user(2):
        assert user_dir("uploads").parts[-2:] == ("2", "uploads")
    assert user_dir("uploads").parts[-2:] == ("1", "uploads")  # the test body runs as person 1


def test_turned_off_login_cant_sign_in_and_loses_its_session(client):
    _add_person("third")
    c = _signed_in("third")
    assert c.get("/api/accounts").status_code == 200
    from app.core.users import Login, users_session

    with users_session() as db:
        db.get(Login, 2).disabled = True
        db.commit()
    assert c.get("/api/accounts").status_code == 401
    from app.main import app

    r = TestClient(app).post("/api/auth/login", json={"username": "third", "password": "second-pass-123"})
    assert r.status_code == 403


def test_no_session_no_data(anon):
    assert anon.get("/api/accounts").status_code == 401
    assert anon.get("/api/overview").status_code == 401


def test_password_change_signs_out_other_sessions(client):
    from app.main import app

    other = TestClient(app)
    assert other.post("/api/auth/login", json={"username": "tester", "password": "test-password"}).status_code == 200
    r = client.post("/api/auth/password", json={"current_password": "test-password", "new_password": "new-pass-456"})
    assert r.status_code == 204
    assert client.get("/api/accounts").status_code == 200  # this one kept
    assert other.get("/api/accounts").status_code == 401


def test_single_user_data_moves_to_the_first_person():
    """Before multi-user: data/moneymap.db with one `user` row, plus uploads / gmail / backups."""
    with tempfile.TemporaryDirectory() as d:
        data = Path(d)
        env = {**os.environ, "MONEYMAP_DATA_DIR": d, "MONEYMAP_ALEMBIC_URL": f"sqlite:///{data / 'moneymap.db'}"}
        run = lambda *a: subprocess.run([sys.executable, "-m", *a], cwd=BACKEND, env=env,  # noqa: E731
                                        capture_output=True, text=True)  # fmt: skip
        assert run("alembic", "upgrade", "head").returncode == 0
        db = sqlite3.connect(data / "moneymap.db")
        db.executescript(
            "INSERT INTO user (id, username, password_hash, session_version, failed_logins) "
            "VALUES (1, 'owner', 'hash-x', 3, 0);"
            "INSERT INTO account (name, type, opening_balance, active) VALUES ('Old bank', 'asset', 100, 1);"
        )
        db.commit()
        db.close()
        (data / "uploads").mkdir()
        (data / "uploads" / "a.pdf").write_bytes(b"%PDF")
        env.pop("MONEYMAP_ALEMBIC_URL")
        r = run("app.cli", "migrate")
        assert r.returncode == 0, r.stderr
        assert "moved the existing data to users/1/" in r.stdout
        assert not (data / "moneymap.db").exists()
        assert (data / "users" / "1" / "uploads" / "a.pdf").exists()
        assert list((data / "before-multi-user").glob("moneymap-*.db"))
        moved = sqlite3.connect(data / "users" / "1" / "moneymap.db")
        assert moved.execute("SELECT name FROM account").fetchall() == [("Old bank",)]
        moved.close()
        users = sqlite3.connect(data / "users.db")
        row = users.execute("SELECT id, username, password_hash, session_version, is_admin FROM login").fetchall()
        users.close()
        assert row == [(1, "owner", "hash-x", 3, 1)]  # same id and version: signed-in browsers stay signed in
        again = run("app.cli", "migrate")
        assert again.returncode == 0 and "moved" not in again.stdout

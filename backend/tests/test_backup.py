"""Backup & restore: a person's own data, and the whole server (admins). Made-up data."""

import io
import json
import zipfile

from fastapi.testclient import TestClient

from .helpers import balance, spend

PW = "test-password"


def _restore(client, name, url="/api/backup/restore", **kw):
    return client.post(url, json={"name": name, "password": PW, "confirm": "RESTORE", **kw})


def _upload(client, data: bytes, filename="b.zip", url="/api/backup/upload"):
    return client.post(f"{url}?filename={filename}", content=data, headers={"Content-Type": "application/octet-stream"})


def test_download_and_restore_my_backup(client, bank):
    from app.db import user_dir

    spend(client, bank, 1_000_00, payee="Cafe")
    (user_dir("uploads") / "a.pdf").write_bytes(b"%PDF-1 test")
    r = client.get("/api/backup/download")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment;")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert {"manifest.json", "moneymap.db", "uploads/a.pdf"} <= set(z.namelist())
    assert json.loads(z.read("manifest.json"))["username"] == "tester"
    backup = r.content

    # things change after the backup …
    spend(client, bank, 500_00, payee="Later")
    client.post("/api/accounts", json={"name": "New wallet", "type": "cash", "opening_balance": 0})
    (user_dir("uploads") / "a.pdf").unlink()
    assert balance(client, bank["id"]) == 10_000_000 - 1_500_00

    up = _upload(client, backup)
    assert up.status_code == 201, up.text
    info = up.json()
    assert info["kind"] == "user" and info["transactions"] == 1 and info["username"] == "tester"
    assert _restore(client, info["name"], confirm="yes").status_code == 422
    assert _restore(client, info["name"], password="wrong").status_code == 400
    done = _restore(client, info["name"])
    assert done.status_code == 200, done.text
    assert balance(client, bank["id"]) == 10_000_000 - 1_000_00  # back to the backup
    assert [a["name"] for a in client.get("/api/accounts").json() if a["type"] in ("asset", "cash")] == ["Bank"]
    assert (user_dir("uploads") / "a.pdf").read_bytes() == b"%PDF-1 test"
    # what was there before was saved first, so the restore can be undone
    files = {f["name"]: f for f in client.get("/api/backup/files").json()}
    first = files[done.json()["saved_first"]]
    assert first["note"] == "Saved before a restore" and first["transactions"] == 2
    assert _restore(client, first["name"]).status_code == 200
    assert balance(client, bank["id"]) == 10_000_000 - 1_500_00


def test_restore_a_plain_db_copy_from_a_reset(client, bank):
    spend(client, bank, 2_000_00)
    r = client.post("/api/reset", json={"mode": "data", "password": PW, "confirm": "RESET"}).json()
    assert client.get("/api/accounts").json() == []
    assert _restore(client, r["backup_file"]).status_code == 200
    assert balance(client, bank["id"]) == 10_000_000 - 2_000_00


def test_bad_files_are_refused(client):
    assert _upload(client, b"not a zip").status_code == 422
    assert _upload(client, b"").status_code == 422
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "moneymap", "kind": "user"}))
        z.writestr("moneymap.db", b"rubbish")
    assert _upload(client, buf.getvalue()).status_code == 422
    assert client.get("/api/backup/files").json() == []  # refused uploads aren't kept
    assert client.get("/api/backup/files/..%2Fmoneymap.db").status_code == 404
    assert _restore(client, "../../users.db").status_code == 404


def test_zip_entries_outside_the_folders_are_ignored(client, bank):
    from app.config import get_settings
    from app.db import user_root

    good = client.get("/api/backup/download").content
    src = zipfile.ZipFile(io.BytesIO(good))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in src.namelist():
            z.writestr(n, src.read(n))
        z.writestr("../evil.txt", b"x")
        z.writestr("uploads/../../evil2.txt", b"x")
        z.writestr("secret_key", b"stolen")
    name = _upload(client, buf.getvalue()).json()["name"]
    assert _restore(client, name).status_code == 200
    data = get_settings().data_dir
    assert not (data / "evil.txt").exists() and not (user_root(1).parent / "evil2.txt").exists()
    assert not (user_root(1) / "secret_key").exists()


def test_only_my_own_files(client):
    from app.main import app

    made = client.post("/api/users", json={"username": "ravi"}).json()
    other = TestClient(app)
    other.post("/api/auth/login", json={"username": "ravi", "password": made["temporary_password"]})
    other.post("/api/auth/password", json={"new_password": "ravis-own-pass"})
    client.post("/api/reset", json={"mode": "data", "password": PW, "confirm": "RESET"})
    assert len(client.get("/api/backup/files").json()) == 1
    assert other.get("/api/backup/files").json() == []
    assert other.get("/api/backup/server/files").status_code == 403
    assert other.get("/api/backup/server/download").status_code == 403


def test_whole_server_backup_and_restore(client, bank):
    from app.main import app

    spend(client, bank, 3_000_00)
    made = client.post("/api/users", json={"username": "ravi"}).json()
    r = client.get("/api/backup/server/download")
    assert r.status_code == 200
    names = set(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert {"manifest.json", "users.db", "secret_key", "users/1/moneymap.db", "users/2/moneymap.db"} <= names
    backup = r.content

    # after the backup: a third person, more spending
    client.post("/api/users", json={"username": "later"})
    spend(client, bank, 1_00)
    up = _upload(client, backup, url="/api/backup/server/upload")
    assert up.status_code == 201, up.text
    assert up.json()["people"] == 2
    assert (
        _upload(client, client.get("/api/backup/download").content, url="/api/backup/server/upload").status_code == 422
    )
    done = _restore(client, up.json()["name"], url="/api/backup/server/restore")
    assert done.status_code == 200, done.text
    assert done.json()["signed_out"] is True
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": "tester", "password": PW}).status_code == 200
    assert balance(c, bank["id"]) == 10_000_000 - 3_000_00
    assert [u["username"] for u in c.get("/api/users").json()] == ["tester", "ravi"]
    files = {f["name"] for f in c.get("/api/backup/server/files").json()}
    assert done.json()["saved_first"] in files  # the server as it was, saved first
    assert (
        c.post("/api/auth/login", json={"username": "ravi", "password": made["temporary_password"]}).status_code == 200
    )

"""Settings → Users: the admin adds people (no public sign-up), resets passwords, turns logins off,
manages the admin role and deletes people. Made-up people."""

from fastapi.testclient import TestClient


def _new_client():
    from app.main import app

    return TestClient(app)


def _add(client, username="ravi", **kw):
    r = client.post("/api/users", json={"username": username, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _sign_in(username, password):
    c = _new_client()
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c, r.json()


def test_admin_adds_a_person_who_must_choose_a_password(client):
    made = _add(client, "ravi", display_name="Ravi K")
    pw = made["temporary_password"]
    assert len(pw) == 14 and made["user"]["must_change_password"] is True and made["user"]["is_admin"] is False
    c, st = _sign_in("ravi", pw)
    assert st["must_change_password"] is True and st["display_name"] == "Ravi K"
    assert c.get("/api/accounts").status_code == 403  # their own password first
    assert c.post("/api/auth/password", json={"new_password": pw}).status_code == 400  # not the same one
    assert c.post("/api/auth/password", json={"new_password": "ravis-own-pass"}).status_code == 204
    assert c.get("/api/auth/status").json()["must_change_password"] is False
    assert c.get("/api/accounts").json() == []  # their own, empty data
    assert len(c.get("/api/categories").json()) == 53
    assert _new_client().post("/api/auth/login", json={"username": "ravi", "password": pw}).status_code == 401


def test_only_admins_manage_users(client):
    pw = _add(client, "meena")["temporary_password"]
    c, _ = _sign_in("meena", pw)
    c.post("/api/auth/password", json={"new_password": "meenas-pass-1"})
    assert c.get("/api/users").status_code == 403
    assert c.post("/api/users", json={"username": "x"}).status_code == 403
    assert _new_client().get("/api/users").status_code == 401


def test_usernames_are_unique_and_simple(client):
    _add(client, "ravi")
    assert client.post("/api/users", json={"username": "RAVI"}).status_code == 409
    assert client.post("/api/users", json={"username": "tester"}).status_code == 409
    assert client.post("/api/users", json={"username": "has space"}).status_code == 422
    assert client.post("/api/users", json={"username": "ok", "password": "short"}).status_code == 422


def test_reset_password_signs_them_out(client):
    made = _add(client, "ravi")
    c, _ = _sign_in("ravi", made["temporary_password"])
    c.post("/api/auth/password", json={"new_password": "ravis-own-pass"})
    assert c.get("/api/accounts").status_code == 200
    r = client.post(f"/api/users/{made['user']['id']}/reset-password").json()
    assert r["user"]["must_change_password"] is True and r["temporary_password"] != made["temporary_password"]
    assert c.get("/api/accounts").status_code == 401
    _sign_in("ravi", r["temporary_password"])
    assert client.post("/api/users/1/reset-password").status_code == 422  # own: under Change password


def test_turn_off_and_on(client):
    made = _add(client, "ravi")
    uid = made["user"]["id"]
    c, _ = _sign_in("ravi", made["temporary_password"])
    assert client.patch(f"/api/users/{uid}", json={"disabled": True}).json()["disabled"] is True
    assert c.get("/api/auth/status").json()["authenticated"] is False
    r = _new_client().post("/api/auth/login", json={"username": "ravi", "password": made["temporary_password"]})
    assert r.status_code == 403
    client.patch(f"/api/users/{uid}", json={"disabled": False})
    _sign_in("ravi", made["temporary_password"])


def test_there_is_always_an_admin(client):
    assert client.patch("/api/users/1", json={"is_admin": False}).status_code == 422
    assert client.patch("/api/users/1", json={"disabled": True}).status_code == 422
    made = _add(client, "second", is_admin=True)
    uid = made["user"]["id"]
    c, _ = _sign_in("second", made["temporary_password"])
    c.post("/api/auth/password", json={"new_password": "second-own-pass"})
    assert c.get("/api/users").status_code == 200  # an admin too
    assert c.patch("/api/users/1", json={"is_admin": False}).json()["is_admin"] is False  # another admin remains
    assert c.patch(f"/api/users/{uid}", json={"is_admin": False}).status_code == 422  # yourself
    assert c.post(f"/api/users/{uid}/delete", json={"confirm": "second"}).status_code == 422


def test_delete_keeps_a_copy_of_their_data(client):
    from app.config import get_settings
    from app.db import user_root

    made = _add(client, "ravi")
    uid = made["user"]["id"]
    c, _ = _sign_in("ravi", made["temporary_password"])
    c.post("/api/auth/password", json={"new_password": "ravis-own-pass"})
    c.post("/api/accounts", json={"name": "Ravi cash", "type": "cash", "opening_balance": 100})
    assert client.post(f"/api/users/{uid}/delete", json={"confirm": "nope"}).status_code == 422
    assert client.post("/api/users/1/delete", json={"confirm": "tester"}).status_code == 422  # yourself
    assert client.post(f"/api/users/{uid}/delete", json={"confirm": "ravi"}).status_code == 204
    assert not user_root(uid).exists()
    kept = list((get_settings().data_dir / "deleted-users").glob(f"ravi-{uid}-*/moneymap.db"))
    assert kept
    assert c.get("/api/accounts").status_code == 401
    assert [u["username"] for u in client.get("/api/users").json()] == ["tester"]
    again = _add(client, "newbie")  # may get the same id: starts empty, not with Ravi's data
    n, _ = _sign_in("newbie", again["temporary_password"])
    n.post("/api/auth/password", json={"new_password": "newbie-pass-1"})
    assert n.get("/api/accounts").json() == []

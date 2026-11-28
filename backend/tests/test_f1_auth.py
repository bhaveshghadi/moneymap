"""F1: first-run setup, login, lockout, sessions, CLI."""
from typer.testing import CliRunner

from app.cli import cli
from app.config import APP_VERSION


def test_health(anon):
    assert anon.get("/api/health").json() == {"status": "ok", "version": APP_VERSION}


def test_first_run_needs_setup(anon):
    s = anon.get("/api/auth/status").json()
    assert s == {"setup_required": True, "authenticated": False, "username": None, "display_name": None,
                 "is_admin": False, "must_change_password": False}  # fmt: skip


def test_setup_signs_in_and_only_runs_once(anon):
    r = anon.post("/api/auth/setup", json={"username": " me ", "password": "long-enough"})
    assert r.status_code == 200
    st = anon.get("/api/auth/status").json()
    assert (st["setup_required"], st["authenticated"], st["username"], st["is_admin"]) == (False, True, "me", True)
    again = anon.post("/api/auth/setup", json={"username": "other", "password": "long-enough"})
    assert again.status_code == 409


def test_setup_rejects_short_password(anon):
    r = anon.post("/api/auth/setup", json={"username": "me", "password": "short"})
    assert r.status_code == 422


def test_logout_and_login(client):
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/status").json()["authenticated"] is False
    bad = client.post("/api/auth/login", json={"username": "tester", "password": "nope"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"username": "tester", "password": "test-password"})
    assert ok.status_code == 200
    assert client.get("/api/auth/status").json()["authenticated"] is True


def test_tampered_cookie_is_ignored(client):
    client.cookies.set("moneymap_session", "garbage")
    assert client.get("/api/auth/status").json()["authenticated"] is False


def test_change_password_signs_out_old_sessions(client):
    old_cookie = client.cookies.get("moneymap_session")
    wrong = client.post("/api/auth/password", json={"current_password": "nope", "new_password": "brand-new-pw"})
    assert wrong.status_code == 400
    r = client.post("/api/auth/password", json={"current_password": "test-password", "new_password": "brand-new-pw"})
    assert r.status_code == 204
    # this client got a fresh cookie and stays signed in
    assert client.get("/api/auth/status").json()["authenticated"] is True
    # the old cookie no longer works
    client.cookies.set("moneymap_session", old_cookie)
    assert client.get("/api/auth/status").json()["authenticated"] is False


def test_password_change_needs_login(anon):
    anon.post("/api/auth/setup", json={"username": "me", "password": "long-enough"})
    anon.post("/api/auth/logout")
    anon.cookies.clear()
    r = anon.post("/api/auth/password", json={"current_password": "long-enough", "new_password": "brand-new-pw"})
    assert r.status_code == 401


def test_cli_reset_password(client):
    res = CliRunner().invoke(cli, ["reset-password", "tester", "--password", "via-cli-pw"])
    assert res.exit_code == 0, res.output
    client.cookies.clear()
    ok = client.post("/api/auth/login", json={"username": "tester", "password": "via-cli-pw"})
    assert ok.status_code == 200
    missing = CliRunner().invoke(cli, ["reset-password", "ghost", "--password", "via-cli-pw"])
    assert missing.exit_code == 1


def test_everything_needs_login(anon):
    for path in ("/api/accounts", "/api/categories", "/api/tags", "/api/transactions", "/api/overview"):
        assert anon.get(path).status_code == 401


def test_lockout_after_five_wrong_passwords(client):
    client.post("/api/auth/logout")
    for _ in range(5):
        assert client.post("/api/auth/login", json={"username": "tester", "password": "nope"}).status_code == 401
    # locked: even the right password is refused for now
    r = client.post("/api/auth/login", json={"username": "tester", "password": "test-password"})
    assert r.status_code == 429 and "Try again in" in r.json()["detail"]
    # the CLI reset clears the lock
    assert CliRunner().invoke(cli, ["reset-password", "tester", "--password", "via-cli-pw"]).exit_code == 0
    assert client.post("/api/auth/login", json={"username": "tester", "password": "via-cli-pw"}).status_code == 200


def test_successful_login_resets_the_counter(client):
    client.post("/api/auth/logout")
    for _ in range(4):
        client.post("/api/auth/login", json={"username": "tester", "password": "nope"})
    assert client.post("/api/auth/login", json={"username": "tester", "password": "test-password"}).status_code == 200
    for _ in range(4):
        assert client.post("/api/auth/login", json={"username": "tester", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "tester", "password": "test-password"}).status_code == 200

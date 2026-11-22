"""The Google OAuth client from the environment (MONEYMAP_GOOGLE_CLIENT_JSON / _ID + _SECRET)
instead of pasted in Settings. Made-up client ids."""

import json

import pytest

from app.config import get_settings
from app.db import SessionLocal
from app.modules.gmail.client import account

ENV_JSON = json.dumps({"installed": {"client_id": "999-env.apps.googleusercontent.com", "client_secret": "env-secret"}})


@pytest.fixture()
def env(monkeypatch):
    def set_env(**values):
        for k in ("MONEYMAP_GOOGLE_CLIENT_JSON", "MONEYMAP_GOOGLE_CLIENT_ID", "MONEYMAP_GOOGLE_CLIENT_SECRET"):
            monkeypatch.delenv(k, raising=False)
        for k, v in values.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()

    yield set_env
    monkeypatch.undo()
    get_settings.cache_clear()


def test_client_from_env_json(client, env):
    env(MONEYMAP_GOOGLE_CLIENT_JSON=ENV_JSON)
    st = client.get("/api/gmail/status").json()
    assert st["client_configured"] and st["client_from_env"] and st["client_id_hint"].startswith("999-env")
    with SessionLocal() as db:
        assert account(db).client_secret == "env-secret"  # kept (encrypted) for the Gmail calls
    # it can't be pasted over or removed in Settings
    assert client.put("/api/gmail/client", json={"json_text": ENV_JSON}).status_code == 409
    assert client.delete("/api/gmail/client").status_code == 409


def test_a_different_env_client_drops_the_old_connection(client, env):
    env(MONEYMAP_GOOGLE_CLIENT_JSON=ENV_JSON)
    with SessionLocal() as db:
        acct = account(db)
        acct.token, acct.email = {"access_token": "x", "refresh_token": "y"}, "me@example.com"
        db.commit()
    env(MONEYMAP_GOOGLE_CLIENT_ID="777-other.apps.googleusercontent.com", MONEYMAP_GOOGLE_CLIENT_SECRET="s2")
    st = client.get("/api/gmail/status").json()
    assert st["client_id_hint"].startswith("777-other") and st["connected"] is False


def test_bad_or_half_env(client, env):
    env(MONEYMAP_GOOGLE_CLIENT_JSON="{not json")
    st = client.get("/api/gmail/status").json()
    assert st["client_from_env"] is False and "valid JSON" in st["client_env_error"]
    env(MONEYMAP_GOOGLE_CLIENT_ID="only-the-id")
    st = client.get("/api/gmail/status").json()
    assert "MONEYMAP_GOOGLE_CLIENT_SECRET" in st["client_env_error"]
    # meanwhile a pasted client still works
    assert client.put("/api/gmail/client", json={"json_text": ENV_JSON}).status_code == 200


def test_no_env_nothing_changes(client, env):
    env()
    st = client.get("/api/gmail/status").json()
    assert st["client_configured"] is False and st["client_from_env"] is False and st["client_env_error"] is None

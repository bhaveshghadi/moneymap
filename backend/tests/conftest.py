import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Point the app at a throwaway data dir BEFORE app modules are imported.
_DATA = Path(tempfile.mkdtemp(prefix="moneymap-test-"))
os.environ["MONEYMAP_DATA_DIR"] = str(_DATA)

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _cleanup():
    yield
    from app.core.users import dispose_users_engine
    from app.db import dispose_all

    dispose_all()
    dispose_users_engine()
    shutil.rmtree(_DATA, ignore_errors=True)


def _wipe():
    """Every login gone and every person's tables emptied (the files and their schema are kept, so
    the next setup is quick): each test starts from a fresh install."""
    from sqlalchemy import delete

    from app.core.users import Login, users_session
    from app.db import Base, engine_for, users_root

    with users_session() as db:
        db.execute(delete(Login))
        db.commit()
    root = users_root()
    for folder in root.iterdir() if root.exists() else []:
        if not folder.name.isdigit():
            continue
        if (folder / "moneymap.db").exists():
            with engine_for(int(folder.name)).begin() as conn:
                for table in reversed(Base.metadata.sorted_tables):
                    conn.execute(table.delete())
        for sub in ("gmail", "backups", "uploads"):
            shutil.rmtree(folder / sub, ignore_errors=True)


@pytest.fixture()
def anon():
    """Client on an empty install (no login yet)."""
    from fastapi.testclient import TestClient

    from app.main import app

    _wipe()
    return TestClient(app)


@pytest.fixture()
def client(anon):
    """Signed-in client on a fresh install. The test body also runs as this person, so it can use
    SessionLocal() directly."""
    from app.db import reset_uid, set_uid

    r = anon.post("/api/auth/setup", json={"username": "tester", "password": "test-password"})
    assert r.status_code == 200, r.text
    token = set_uid(1)
    yield anon
    reset_uid(token)


@pytest.fixture()
def bank(client):
    """A bank account holding ₹1,00,000."""
    return client.post("/api/accounts", json={"name": "Bank", "type": "asset", "opening_balance": 10_000_000}).json()

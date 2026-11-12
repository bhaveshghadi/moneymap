import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Point the app at a throwaway data dir BEFORE app modules are imported.
_DATA = Path(tempfile.mkdtemp(prefix="moneymap-test-"))
os.environ["MONEYMAP_DATA_DIR"] = str(_DATA)

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    """Build the test database with the real migrations (not create_all)."""
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True, capture_output=True)
    yield
    from app.db import engine

    engine.dispose()
    shutil.rmtree(_DATA, ignore_errors=True)


def _wipe():
    """Empty every table so each test starts from a fresh install."""
    from app.db import Base, engine

    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def anon():
    """Client on an empty database (no user yet)."""
    from fastapi.testclient import TestClient

    from app.main import app

    _wipe()
    return TestClient(app)


@pytest.fixture()
def client(anon):
    """Signed-in client on a fresh database."""
    r = anon.post("/api/auth/setup", json={"username": "tester", "password": "test-password"})
    assert r.status_code == 200, r.text
    return anon


@pytest.fixture()
def bank(client):
    """A bank account holding ₹1,00,000."""
    return client.post("/api/accounts", json={"name": "Bank", "type": "asset", "opening_balance": 10_000_000}).json()

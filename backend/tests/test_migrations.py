"""Migrations must work on existing data."""

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def _alembic(data_dir: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "MONEYMAP_DATA_DIR": data_dir,
           "MONEYMAP_ALEMBIC_URL": f"sqlite:///{Path(data_dir) / 'moneymap.db'}"}  # fmt: skip
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True
    )


def _sql(data_dir: str, script: str) -> None:
    db = sqlite3.connect(Path(data_dir) / "moneymap.db")
    db.executescript(script)
    db.commit()
    db.close()


def test_0005_deletes_unused_liabilities_and_keeps_the_rest():
    with tempfile.TemporaryDirectory() as d:
        assert _alembic(d, "upgrade", "0004_f4_transactions").returncode == 0
        _sql(
            d,
            "INSERT INTO account (name, type, opening_balance, active, liability_kind) VALUES "
            "('SBI', 'asset', 100, 1, NULL), ('Card', 'liability', -50, 1, 'card'), ('Loan', 'liability', -9, 1, 'loan');",
        )
        r = _alembic(d, "upgrade", "head")
        assert r.returncode == 0, r.stderr
        db = sqlite3.connect(Path(d) / "moneymap.db")
        assert db.execute("SELECT name, type FROM account").fetchall() == [("SBI", "asset")]
        assert "liability_kind" not in [c[1] for c in db.execute("PRAGMA table_info(account)")]
        db.close()


def test_0005_refuses_when_a_liability_has_transactions():
    with tempfile.TemporaryDirectory() as d:
        assert _alembic(d, "upgrade", "0004_f4_transactions").returncode == 0
        _sql(
            d,
            "INSERT INTO account (id, name, type, opening_balance, active) VALUES "
            "(1, 'Card', 'liability', 0, 1), (2, 'Shop', 'expense', 0, 1);"
            'INSERT INTO "transaction" (type, date, amount, description, source_id, destination_id) '
            "VALUES ('withdrawal', '2026-11-01', 100, 'x', 1, 2);",
        )
        r = _alembic(d, "upgrade", "head")
        assert r.returncode != 0 and "use a liability account" in r.stderr


def test_0013_adds_card_fee_category_to_existing_categories():
    with tempfile.TemporaryDirectory() as d:
        assert _alembic(d, "upgrade", "0012_credit_cards").returncode == 0
        _sql(d, "INSERT INTO category (name, kind, icon, color, essential) VALUES ('Rent', 'expense', 'key', 'indigo', 1);")
        r = _alembic(d, "upgrade", "0013_card_statements")
        assert r.returncode == 0, r.stderr
        db = sqlite3.connect(Path(d) / "moneymap.db")
        names = [n for (n,) in db.execute("SELECT name FROM category ORDER BY id")]
        db.close()
        assert names == ["Rent", "Card Fees & Interest"]
        r = _alembic(d, "upgrade", "head")  # 0015 adds Loan Interest the same way
        assert r.returncode == 0, r.stderr
        db = sqlite3.connect(Path(d) / "moneymap.db")
        assert [n for (n,) in db.execute("SELECT name FROM category ORDER BY id")][-1] == "Loan Interest"
        db.close()

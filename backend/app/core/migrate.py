"""Bring every person's database up to the latest schema (Alembic, one file at a time).

Start-up runs `python -m app.cli migrate`: the single-user data is moved to users/<id>/ the first
time, then each user's file is upgraded. A new user's file is created the same way."""

import sqlite3
from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from ..db import dispose_engine, user_db_path, user_root
from .users import adopt_single_user_data, all_user_ids

BACKEND = Path(__file__).resolve().parent.parent.parent


def alembic_config(db_path: Path) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["url"] = f"sqlite:///{db_path}"
    return cfg


@lru_cache
def head() -> str:
    return ScriptDirectory.from_config(alembic_config(BACKEND / "unused.db")).get_current_head()


def revision_of(path: Path) -> str | None:
    if not path.exists():
        return None
    con = sqlite3.connect(path)
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'").fetchone():
            return None
        row = con.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else None
    finally:
        con.close()


def migrate_user(uid: int) -> bool:
    """Create or upgrade this user's database. True when something was done."""
    path = user_db_path(uid)
    if revision_of(path) == head():
        return False
    user_root(uid).mkdir(parents=True, exist_ok=True)
    dispose_engine(uid)  # no open connection while tables are rebuilt
    command.upgrade(alembic_config(path), "head")
    return True


def migrate_all(log=print) -> None:  # noqa: ANN001
    adopt_single_user_data(log)
    for uid in all_user_ids():
        if migrate_user(uid):
            log(f"user {uid}: database upgraded to {head()}")

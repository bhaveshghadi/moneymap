"""The logins database (<data_dir>/users.db): who can sign in. No money data here.

Each login's data is its own file (app/db.py). The admin creates people (no public sign-up);
an admin manages logins only and can't open anyone else's data.

Schema changes: bump SCHEMA_VERSION and add a step to `_upgrade` (a tiny file needs no Alembic).
"""

import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Engine, Integer, String, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from ..config import get_settings

SCHEMA_VERSION = 1


class UsersBase(DeclarativeBase):
    pass


class Login(UsersBase):
    __tablename__ = "login"
    id: Mapped[int] = mapped_column(primary_key=True)  # also the folder name: users/<id>/
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # Bumped on password change: sessions carrying an older version stop working.
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)  # UTC
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)  # UTC
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


_engine: Engine | None = None
_lock = threading.Lock()


def users_db_path() -> Path:
    return get_settings().data_dir / "users.db"


def users_engine() -> Engine:
    global _engine
    with _lock:
        if _engine is None:
            from ..db import sqlite_engine

            _engine = sqlite_engine(users_db_path())
            UsersBase.metadata.create_all(_engine)
            with _engine.begin() as c:
                if c.execute(text("PRAGMA user_version")).scalar() < SCHEMA_VERSION:
                    c.execute(text(f"PRAGMA user_version = {SCHEMA_VERSION}"))
        return _engine


def dispose_users_engine() -> None:
    global _engine
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


def users_session() -> Session:
    return Session(bind=users_engine(), autoflush=False, expire_on_commit=False)


def login_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Login)) or 0


def all_user_ids() -> list[int]:
    with users_session() as db:
        return list(db.scalars(select(Login.id).order_by(Login.id)))


# ---------------------------------------------------------------- one-time move to per-user files


def adopt_single_user_data(log=print) -> int | None:  # noqa: ANN001
    """Before multi-user, everything was <data_dir>/moneymap.db (+ uploads, gmail, backups) with one
    row in its `user` table. Move it to users/<that id>/ and make that person the admin login.
    A copy of the old database is kept in <data_dir>/before-multi-user/. Runs once; returns the id."""
    data = get_settings().data_dir
    old = data / "moneymap.db"
    if not old.exists():
        return None
    with users_session() as db:
        if login_count(db):
            log(f"users.db already has logins; leaving {old} where it is")
            return None
    con = sqlite3.connect(old)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # everything into the main file before it moves
        row = None
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user'").fetchone():
            row = con.execute(
                "SELECT id, username, password_hash, session_version, created_at FROM user ORDER BY id LIMIT 1"
            ).fetchone()
        keep = data / "before-multi-user"
        keep.mkdir(parents=True, exist_ok=True)
        dest = sqlite3.connect(keep / f"moneymap-{datetime.now():%Y-%m-%d-%H%M%S}.db")
        try:
            con.backup(dest)
        finally:
            dest.close()
    finally:
        con.close()
    uid = row[0] if row else 1
    target = data / "users" / str(uid)
    target.mkdir(parents=True, exist_ok=True)
    shutil.move(str(old), str(target / "moneymap.db"))
    for side in ("moneymap.db-wal", "moneymap.db-shm"):
        (data / side).unlink(missing_ok=True)
    for folder in ("uploads", "gmail", "backups"):
        if (data / folder).exists():
            shutil.move(str(data / folder), str(target / folder))
    if row:
        with users_session() as db:
            created = datetime.fromisoformat(str(row[4])) if row[4] else None
            db.add(
                Login(
                    id=uid,
                    username=row[1],
                    password_hash=row[2],
                    session_version=row[3] or 1,
                    is_admin=True,
                    **({"created_at": created} if created else {}),
                )
            )
            db.commit()
        log(f"moved the existing data to users/{uid}/ — {row[1]!r} is the admin")
    else:
        log(f"moved the existing (not set up) database to users/{uid}/")
    return uid

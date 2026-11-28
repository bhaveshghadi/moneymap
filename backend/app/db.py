"""Databases. Each person's money lives in their own SQLite file:

    <data_dir>/users.db                      logins only (see app/core/users.py)
    <data_dir>/users/<id>/moneymap.db        that person's data
    <data_dir>/users/<id>/{uploads,gmail,backups}

A request runs "as" the signed-in user (a context variable set by the session middleware), and
`get_db` / `SessionLocal` open that user's file — so the queries everywhere stay as they were and
one person's data can never reach another's. Background work sets the user with `as_user(id)`.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session

from .config import get_settings

_uid: ContextVar[int | None] = ContextVar("moneymap_uid", default=None)
_engines: dict[int, Engine] = {}
_lock = threading.Lock()


class Base(DeclarativeBase):
    pass


def _sqlite_pragmas(dbapi_conn, _record) -> None:  # noqa: ANN001
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


def sqlite_engine(path: Path) -> Engine:
    e = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    event.listen(e, "connect", _sqlite_pragmas)
    return e


def users_root() -> Path:
    return get_settings().data_dir / "users"


def user_root(uid: int) -> Path:
    return users_root() / str(uid)


def user_db_path(uid: int) -> Path:
    return user_root(uid) / "moneymap.db"


def current_uid() -> int:
    uid = _uid.get()
    if uid is None:
        raise RuntimeError("No user for this work (set by the session middleware or as_user)")
    return uid


def signed_in_uid() -> int | None:
    return _uid.get()


def set_uid(uid: int | None):
    """Low level (the middleware): returns a token for `reset_uid`."""
    return _uid.set(uid)


def reset_uid(token) -> None:  # noqa: ANN001
    _uid.reset(token)


@contextmanager
def as_user(uid: int) -> Iterator[None]:
    """Run a block (a background job, a CLI command) as this user."""
    token = _uid.set(uid)
    try:
        yield
    finally:
        _uid.reset(token)


def user_dir(name: str) -> Path:
    """A folder of the current user's: uploads, gmail, backups."""
    d = user_root(current_uid()) / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def engine_for(uid: int) -> Engine:
    with _lock:
        e = _engines.get(uid)
        if e is None:
            user_root(uid).mkdir(parents=True, exist_ok=True)
            e = _engines[uid] = sqlite_engine(user_db_path(uid))
        return e


def dispose_engine(uid: int) -> None:
    with _lock:
        e = _engines.pop(uid, None)
    if e is not None:
        e.dispose()


def dispose_all() -> None:
    with _lock:
        engines = list(_engines.values())
        _engines.clear()
    for e in engines:
        e.dispose()


def SessionLocal() -> Session:  # noqa: N802  (kept the sessionmaker's name: used everywhere)
    """A session on the current user's database."""
    return Session(bind=engine_for(current_uid()), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    if _uid.get() is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

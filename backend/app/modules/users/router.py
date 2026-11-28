"""Settings → Users (admins only): add people, reset a password, turn a login off / on, admin role,
delete. Like Immich: no public sign-up — the admin adds everyone. An admin manages logins only and
can't open anyone else's data (each person's data is their own file)."""

import secrets
import shutil
import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.users import Login, users_session
from ...db import dispose_engine, user_db_path, user_root
from ..auth.security import current_user, hash_password
from ..auth.service import prepare_user_data
from .schemas import UserCreated, UserDelete, UserIn, UserOut, UserPatch

router = APIRouter(prefix="/users", tags=["users"])

# no look-alike characters (0/O, 1/l/I) in a password read off a screen
_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def admin(user: Login = Depends(current_user)) -> Login:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an admin can manage users.")
    return user


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def temporary_password() -> str:
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3))


def _out(u: Login) -> UserOut:
    return UserOut(
        id=u.id,
        username=u.username,
        display_name=u.display_name,
        is_admin=u.is_admin,
        disabled=u.disabled,
        must_change_password=u.must_change_password,
        locked=bool(u.locked_until and u.locked_until > _now()),
        created_at=u.created_at,
        last_login_at=u.last_login_at,
    )


def _get(db: Session, uid: int) -> Login:
    u = db.get(Login, uid)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return u


def _other_active_admins(db: Session, uid: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Login)
            .where(Login.is_admin.is_(True), Login.disabled.is_(False), Login.id != uid)
        )
        or 0
    )


@router.get("", response_model=list[UserOut])
def list_users(_: Login = Depends(admin)) -> list[UserOut]:
    with users_session() as db:
        return [_out(u) for u in db.scalars(select(Login).order_by(Login.id))]


@router.post("", response_model=UserCreated, status_code=201)
def add_user(body: UserIn, _: Login = Depends(admin)) -> UserCreated:
    name = body.username.strip()
    pw = body.password or temporary_password()
    with users_session() as db:
        if db.scalar(select(Login.id).where(func.lower(Login.username) == name.lower())):
            raise HTTPException(status.HTTP_409_CONFLICT, f"The username “{name}” is taken.")
        u = Login(
            username=name,
            display_name=(body.display_name or "").strip() or None,
            password_hash=hash_password(pw),
            is_admin=body.is_admin,
            must_change_password=True,  # they choose their own at the first sign-in
        )
        db.add(u)
        db.commit()
    old = user_root(u.id)
    if old.exists():  # a folder left from someone deleted outside the app: never hand it to a new person
        dispose_engine(u.id)
        bin_ = get_settings().data_dir / "deleted-users"
        bin_.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(bin_ / f"orphan-{u.id}-{_now():%Y%m%d%H%M%S}"))
    prepare_user_data(u.id)
    return UserCreated(user=_out(u), temporary_password=pw)


@router.post("/{uid}/reset-password", response_model=UserCreated)
def reset_password(uid: int, me: Login = Depends(admin)) -> UserCreated:
    if uid == me.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Change your own password under Change password.")
    pw = temporary_password()
    with users_session() as db:
        u = _get(db, uid)
        u.password_hash = hash_password(pw)
        u.must_change_password = True
        u.session_version += 1  # signed out everywhere
        u.failed_logins = 0
        u.locked_until = None
        db.commit()
    return UserCreated(user=_out(u), temporary_password=pw)


@router.patch("/{uid}", response_model=UserOut)
def edit_user(uid: int, body: UserPatch, me: Login = Depends(admin)) -> UserOut:
    data = body.model_dump(exclude_unset=True)
    with users_session() as db:
        u = _get(db, uid)
        if uid == me.id and (data.get("disabled") or data.get("is_admin") is False):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "You can't turn off or demote yourself.")
        losing_admin = u.is_admin and (data.get("is_admin") is False or data.get("disabled"))
        if losing_admin and _other_active_admins(db, uid) == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "There must always be an admin who can sign in.")
        if "display_name" in data:
            u.display_name = (data["display_name"] or "").strip() or None
        if "is_admin" in data and data["is_admin"] is not None:
            u.is_admin = data["is_admin"]
        if "disabled" in data and data["disabled"] is not None:
            u.disabled = data["disabled"]
            if u.disabled:
                u.session_version += 1  # signed out now
        db.commit()
    return _out(u)


@router.post("/{uid}/delete", status_code=204)
def delete_user(uid: int, body: UserDelete, me: Login = Depends(admin)) -> None:
    """Their login goes and their data file moves to deleted-users/ (a copy kept, not erased)."""
    if uid == me.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "You can't delete yourself.")
    with users_session() as db:
        u = _get(db, uid)
        if body.confirm.strip() != u.username:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Type {u.username} to confirm.")
        if u.is_admin and _other_active_admins(db, uid) == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "There must always be an admin who can sign in.")
        username = u.username
        db.delete(u)
        db.commit()
    keep = get_settings().data_dir / "deleted-users" / f"{username}-{uid}-{_now():%Y%m%d%H%M%S}"
    keep.mkdir(parents=True, exist_ok=True)
    path = user_db_path(uid)
    if path.exists():
        src = sqlite3.connect(path)
        try:
            src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            src.close()
    dispose_engine(uid)
    root = user_root(uid)
    if root.exists():
        for item in root.iterdir():
            shutil.move(str(item), str(keep / item.name))
        root.rmdir()

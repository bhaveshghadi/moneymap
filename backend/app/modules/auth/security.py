"""Single-user auth: argon2 password hashes + a signed HttpOnly session cookie."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from ...config import get_settings
from ...db import get_db
from .models import User

COOKIE = "moneymap_session"
_hasher = PasswordHasher()


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().resolved_secret_key(), salt="moneymap-session")


def set_session(resp: Response, user: User) -> None:
    s = get_settings()
    token = _serializer().dumps({"uid": user.id, "v": user.session_version})
    resp.set_cookie(
        COOKIE,
        token,
        max_age=s.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=s.cookie_secure,
        path="/",
    )


def clear_session(resp: Response) -> None:
    resp.delete_cookie(COOKIE, path="/")


def user_from_request(request: Request, db: Session) -> User | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=get_settings().session_days * 86400)
    except BadSignature:
        return None
    user = db.get(User, data.get("uid"))
    if user is None or user.session_version != data.get("v"):
        return None
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Dependency for every protected router."""
    user = user_from_request(request, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return user

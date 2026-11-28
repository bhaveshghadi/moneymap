"""Auth: argon2 password hashes + a signed HttpOnly session cookie {uid, v}.

Logins live in users.db (app/core/users.py). `SessionUserMiddleware` reads the cookie on every
request and, for a valid login, runs the request as that user — so `get_db` opens their file."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer

from ...config import get_settings
from ...core.users import Login, users_session
from ...db import reset_uid, set_uid, signed_in_uid

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


def set_session(resp: Response, user: Login) -> None:
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


def login_from_token(token: str | None) -> Login | None:
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=get_settings().session_days * 86400)
    except BadSignature:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("uid"), int):
        return None
    with users_session() as db:
        user = db.get(Login, data["uid"])
    if user is None or user.disabled or user.session_version != data.get("v"):
        return None
    return user


def user_from_request(request: Request) -> Login | None:
    return login_from_token(request.cookies.get(COOKIE))


def current_user(request: Request) -> Login:
    """Dependency for every protected router: the login this request runs as. Someone still on the
    temporary password the admin gave them can only choose their own (under /api/auth) first."""
    uid = signed_in_uid()
    user = None
    if uid is not None:
        with users_session() as db:
            user = db.get(Login, uid)
    if user is None or user.disabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    if user.must_change_password and not request.url.path.startswith("/api/auth/"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Choose your own password first.")
    return user


def _cookie(scope) -> str | None:  # noqa: ANN001
    for k, v in scope.get("headers") or []:
        if k == b"cookie":
            for part in v.decode("latin-1").split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE:
                    return value
    return None


class SessionUserMiddleware:
    """Plain ASGI middleware (keeps the context variable for everything the request runs)."""

    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        user = login_from_token(_cookie(scope))
        token = set_uid(user.id if user else None)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_uid(token)

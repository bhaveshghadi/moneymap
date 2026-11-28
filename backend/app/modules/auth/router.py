from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from ...config import get_settings
from ...core.users import Login, login_count, users_session
from .schemas import AuthStatus, Credentials, PasswordChange, SetupIn
from .security import clear_session, current_user, hash_password, set_session, user_from_request, verify_password
from .service import prepare_user_data

router = APIRouter(prefix="/auth", tags=["auth"])


def _now() -> datetime:
    """Naive UTC, matching how SQLite stores DateTime columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def _status(user: Login | None) -> AuthStatus:
    return AuthStatus(
        setup_required=False,
        authenticated=user is not None,
        username=user.username if user else None,
        display_name=user.display_name if user else None,
        is_admin=bool(user and user.is_admin),
        must_change_password=bool(user and user.must_change_password),
    )


@router.get("/status", response_model=AuthStatus)
def auth_status(request: Request) -> AuthStatus:
    with users_session() as db:
        if login_count(db) == 0:
            return AuthStatus(setup_required=True, authenticated=False)
    return _status(user_from_request(request))


@router.post("/setup", response_model=AuthStatus)
def setup(body: SetupIn, response: Response) -> AuthStatus:
    """First run only: the first person, who is the admin (they add everyone else)."""
    with users_session() as db:
        if login_count(db) > 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "Setup has already been completed")
        user = Login(username=body.username.strip(), password_hash=hash_password(body.password), is_admin=True)
        user.last_login_at = _now()
        db.add(user)
        db.commit()
    prepare_user_data(user.id)
    set_session(response, user)
    return _status(user)


@router.post("/login", response_model=AuthStatus)
def login(body: Credentials, response: Response) -> AuthStatus:
    s = get_settings()
    with users_session() as db:
        user = db.scalar(select(Login).where(Login.username == body.username.strip()))
        if user is not None and user.locked_until and user.locked_until > _now():
            minutes = max(1, int((user.locked_until - _now()).total_seconds() // 60) + 1)
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, f"Too many wrong passwords. Try again in {minutes} minute(s)."
            )
        if user is None or not verify_password(body.password, user.password_hash):
            if user is not None:
                user.failed_logins += 1
                if user.failed_logins >= s.max_failed_logins:
                    user.locked_until = _now() + timedelta(minutes=s.lockout_minutes)
                    user.failed_logins = 0
                db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
        if user.disabled:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is turned off. Ask your admin.")
        user.failed_logins = 0
        user.locked_until = None
        user.last_login_at = _now()
        db.commit()
    set_session(response, user)
    return _status(user)


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    clear_session(response)


@router.post("/password", status_code=204)
def change_password(body: PasswordChange, response: Response, user: Login = Depends(current_user)) -> None:
    if not user.must_change_password and not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a password different from the current one")
    with users_session() as db:
        me = db.get(Login, user.id)
        me.password_hash = hash_password(body.new_password)
        me.session_version += 1  # signs out every other session
        me.must_change_password = False
        db.commit()
    set_session(response, me)  # …but keeps this one signed in

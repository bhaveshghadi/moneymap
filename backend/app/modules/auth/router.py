from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...db import get_db
from ..categories.seed import seed_categories
from .models import Setting, User
from .schemas import AuthStatus, Credentials, PasswordChange, SetupIn
from .security import clear_session, current_user, hash_password, set_session, user_from_request, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _now() -> datetime:
    """Naive UTC, matching how SQLite stores DateTime columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def _user_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User)) or 0


@router.get("/status", response_model=AuthStatus)
def auth_status(request: Request, db: Session = Depends(get_db)) -> AuthStatus:
    if _user_count(db) == 0:
        return AuthStatus(setup_required=True, authenticated=False)
    user = user_from_request(request, db)
    return AuthStatus(setup_required=False, authenticated=user is not None, username=user.username if user else None)


@router.post("/setup", response_model=AuthStatus)
def setup(body: SetupIn, response: Response, db: Session = Depends(get_db)) -> AuthStatus:
    """First run only: create the single user and the starter categories."""
    if _user_count(db) > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup has already been completed")
    user = User(username=body.username.strip(), password_hash=hash_password(body.password))
    db.add(user)
    seed_categories(db)
    from ..guide.service import SETUP_KEY

    db.add(Setting(key=SETUP_KEY, value="pending"))  # a brand-new install: show the setup page first
    db.commit()
    set_session(response, user)
    return AuthStatus(setup_required=False, authenticated=True, username=user.username)


@router.post("/login", response_model=AuthStatus)
def login(body: Credentials, response: Response, db: Session = Depends(get_db)) -> AuthStatus:
    s = get_settings()
    user = db.scalar(select(User).where(User.username == body.username.strip()))
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
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    set_session(response, user)
    return AuthStatus(setup_required=False, authenticated=True, username=user.username)


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    clear_session(response)


@router.post("/password", status_code=204)
def change_password(
    body: PasswordChange,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    user.session_version += 1  # signs out every other session
    db.commit()
    set_session(response, user)  # …but keeps this one signed in

"""Settings → Reset.

"data": deletes all money data (accounts, transactions, categories, tags, budgets …)
but keeps the login and settings; the starter categories are added again.
"everything": factory reset — the login goes too, and the app shows first-run
setup afterwards.

A copy of the database is written to <data_dir>/backups first unless switched off.
"""

import logging
import sqlite3
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ...config import get_settings
from ...db import Base, get_db
from ..auth.models import User
from ..auth.security import clear_session, current_user, verify_password
from ..categories.seed import seed_categories

log = logging.getLogger("moneymap.reset")
router = APIRouter(prefix="/reset", tags=["reset"])

# Tables a data-only reset keeps.
KEEP_ON_DATA_RESET = {"user", "setting"}
CONFIRM_WORD = "RESET"


class ResetIn(BaseModel):
    mode: Literal["data", "everything"]
    password: str
    confirm: str
    backup: bool = True


class ResetOut(BaseModel):
    mode: str
    backup_file: str | None  # file name inside <data_dir>/backups
    signed_out: bool


def _backup(db: Session, mode: str) -> str:
    folder = get_settings().data_dir / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"moneymap-{datetime.now():%Y-%m-%d-%H%M%S}-before-reset-{mode}.db"
    raw = db.connection().connection.driver_connection  # the live sqlite3 connection
    dest = sqlite3.connect(path)
    try:
        raw.backup(dest)
    finally:
        dest.close()
    return path.name


@router.post("", response_model=ResetOut)
def reset(
    body: ResetIn,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ResetOut:
    if body.confirm.strip() != CONFIRM_WORD:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Type {CONFIRM_WORD} to confirm.")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password is wrong.")

    backup_file = _backup(db, body.mode) if body.backup else None

    # Children before parents, so foreign keys never block a delete.
    for table in reversed(Base.metadata.sorted_tables):
        if body.mode == "data" and table.name in KEEP_ON_DATA_RESET:
            continue
        db.execute(delete(table))
    if body.mode == "data":
        seed_categories(db)
    db.commit()

    if body.mode == "everything":
        clear_session(response)
    log.warning("reset (%s) done; backup=%s", body.mode, backup_file)
    return ResetOut(mode=body.mode, backup_file=backup_file, signed_out=body.mode == "everything")

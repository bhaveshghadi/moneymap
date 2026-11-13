"""Settings → Reset.

"data": deletes all money data (accounts, transactions, categories, tags, budgets …)
but keeps the login, settings, the Gmail connection and the Inbox (emails turn
"new" again); the starter categories are added again.
"everything": factory reset — the login, Gmail connection (revoked at Google) and
fetched emails go too, and the app shows first-run setup afterwards.

A copy of the database is written to <data_dir>/backups first unless switched off.
"""

import logging
import shutil
import sqlite3
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from ...config import get_settings
from ...db import Base, get_db
from ..auth.models import User
from ..auth.security import clear_session, current_user, verify_password
from ..categories.seed import seed_categories
from ..gmail import client as gmail_client
from ..gmail.fetch import attachments_dir
from ..gmail.models import GmailMessage, GmailRun

log = logging.getLogger("moneymap.reset")
router = APIRouter(prefix="/reset", tags=["reset"])

# Tables a data-only reset keeps.
KEEP_ON_DATA_RESET = {"user", "setting", "gmail_account", "gmail_run", "gmail_message", "gmail_attachment"}
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

    if db.query(GmailRun).filter(GmailRun.status.in_(["running", "cancelling"])).count():
        raise HTTPException(status.HTTP_409_CONFLICT, "A Gmail fetch is running — wait for it or cancel it first.")

    backup_file = _backup(db, body.mode) if body.backup else None
    if body.mode == "everything":
        gmail_client.disconnect(db)  # revokes MoneyMap's Gmail access at Google (best effort)

    # Children before parents, so foreign keys never block a delete.
    for table in reversed(Base.metadata.sorted_tables):
        if body.mode == "data" and table.name in KEEP_ON_DATA_RESET:
            continue
        db.execute(delete(table))
    if body.mode == "data":
        # Emails that pointed at (now deleted) transactions are new again.
        db.execute(update(GmailMessage).where(GmailMessage.status == "handled").values(status="new"))
        seed_categories(db)
    db.commit()
    # Uploaded statement PDFs belonged to the (now deleted) statement imports.
    shutil.rmtree(get_settings().data_dir / "uploads", ignore_errors=True)
    if body.mode == "everything":
        shutil.rmtree(attachments_dir(), ignore_errors=True)

    if body.mode == "everything":
        clear_session(response)
    log.warning("reset (%s) done; backup=%s", body.mode, backup_file)
    return ResetOut(mode=body.mode, backup_file=backup_file, signed_out=body.mode == "everything")

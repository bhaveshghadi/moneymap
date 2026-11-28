"""Settings → Reset.

"data": deletes all money data (accounts, transactions, categories, tags, budgets …)
but keeps the login, settings, the Gmail connection and the Inbox (emails turn
"new" again); the starter categories are added again.
"everything": this person's whole file — settings, Gmail connection (revoked at Google) and
fetched emails go too, and the setup page shows again. The login stays (it's in users.db), and
other people's data is never touched (each has their own file).

A copy of the database is written to users/<id>/backups first unless switched off.
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

from ...core.users import Login
from ...db import Base, get_db, user_dir
from ..auth.security import current_user, verify_password
from ..auth.service import prepare_user_data
from ..categories.seed import seed_categories
from ..gmail import client as gmail_client
from ..gmail.fetch import attachments_dir
from ..gmail.models import GmailMessage, GmailRun

log = logging.getLogger("moneymap.reset")
router = APIRouter(prefix="/reset", tags=["reset"])

# Tables a data-only reset keeps.
KEEP_ON_DATA_RESET = {
    "setting",
    "gmail_account",
    "gmail_mailbox",
    "gmail_run",
    "gmail_message",
    "gmail_attachment",
}
CONFIRM_WORD = "RESET"


class ResetIn(BaseModel):
    mode: Literal["data", "everything"]
    password: str
    confirm: str
    backup: bool = True


class ResetOut(BaseModel):
    mode: str
    backup_file: str | None  # file name inside users/<id>/backups
    signed_out: bool


def _backup(db: Session, mode: str) -> str:
    path = user_dir("backups") / f"moneymap-{datetime.now():%Y-%m-%d-%H%M%S}-before-reset-{mode}.db"
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
    user: Login = Depends(current_user),
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
    shutil.rmtree(user_dir("uploads"), ignore_errors=True)
    if body.mode == "everything":
        shutil.rmtree(attachments_dir(), ignore_errors=True)
        prepare_user_data(user.id)  # starter categories, and the setup page again
    log.warning("reset (%s) for user %s done; backup=%s", body.mode, user.id, backup_file)
    return ResetOut(mode=body.mode, backup_file=backup_file, signed_out=False)

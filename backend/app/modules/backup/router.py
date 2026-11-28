"""Settings → Backup & restore.

Your data:     download a backup now; upload one; the saved list (automatic copies made before a
               reset or restore, and uploads); restore one (password + type RESTORE).
Whole server:  admins only — the same for every person, the logins and the secret key."""

import os
import secrets
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from ...core.users import Login
from ...db import SessionLocal
from ..auth.security import clear_session, current_user, verify_password
from ..gmail.models import GmailRun
from ..users.router import admin
from .service import (
    MAX_UPLOAD,
    NAME_RE,
    BackupError,
    Summary,
    backups_dir,
    restore_server,
    restore_user,
    server_backups_dir,
    stamp,
    summarize,
    write_server_backup,
    write_user_backup,
)

router = APIRouter(prefix="/backup", tags=["backup"])
CONFIRM_WORD = "RESTORE"


class BackupFile(BaseModel):
    name: str
    size: int
    saved_at: datetime
    kind: str  # user | server
    note: str  # how it got here
    created: str | None = None  # when the backup was made (from inside it)
    username: str | None = None
    transactions: int | None = None
    accounts: int | None = None
    last_date: str | None = None
    people: int | None = None
    problem: str | None = None  # can't be restored, and why


class RestoreIn(BaseModel):
    name: str
    password: str
    confirm: str


class RestoreOut(BaseModel):
    restored: str
    saved_first: str  # the copy of what was there before
    signed_out: bool = False


def _bad(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


def _note(name: str) -> str:
    if "before-restore" in name:
        return "Saved before a restore"
    if "before-reset" in name:
        return "Saved before a reset"
    if "before-multi-user" in name:
        return "Saved before the move to multi-user"
    if name.startswith("uploaded-"):
        return "Uploaded"
    return "Saved"


def _info(path: Path, kind: str) -> BackupFile:
    st = path.stat()
    out = BackupFile(
        name=path.name, size=st.st_size, saved_at=datetime.fromtimestamp(st.st_mtime), kind=kind, note=_note(path.name)
    )
    try:
        s: Summary = summarize(path)
        out.kind, out.created, out.username = s.kind, s.created, s.username
        out.transactions, out.accounts, out.last_date, out.people = s.transactions, s.accounts, s.last_date, s.people
    except BackupError as e:
        out.problem = str(e)
    return out


def _file(folder: Path, name: str) -> Path:
    if not NAME_RE.match(name):
        raise _bad("No such backup", status.HTTP_404_NOT_FOUND)
    path = folder / name
    if not path.is_file():
        raise _bad("No such backup", status.HTTP_404_NOT_FOUND)
    return path


def _list(folder: Path, kind: str) -> list[BackupFile]:
    files = [p for p in folder.iterdir() if p.is_file() and NAME_RE.match(p.name)]
    return [_info(p, kind) for p in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)]


def _check_password(user: Login, body: RestoreIn) -> None:
    if body.confirm.strip() != CONFIRM_WORD:
        raise _bad(f"Type {CONFIRM_WORD} to confirm.")
    if not verify_password(body.password, user.password_hash):
        raise _bad("Password is wrong.", status.HTTP_400_BAD_REQUEST)


def _no_fetch_running() -> None:
    with SessionLocal() as db:
        if db.query(GmailRun).filter(GmailRun.status.in_(["running", "cancelling"])).count():
            raise _bad("A Gmail fetch is running — wait for it or cancel it first.", status.HTTP_409_CONFLICT)


async def _receive(request: Request, dest: Path) -> None:
    """The file is sent as the raw request body (no form encoding), up to MAX_UPLOAD."""
    size = 0
    try:
        with open(dest, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise _bad("That file is larger than 2 GB.", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
                f.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    if size == 0:
        dest.unlink(missing_ok=True)
        raise _bad("The file is empty.")


def _download(path: Path, filename: str, remove: bool) -> FileResponse:
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
        background=BackgroundTask(path.unlink, missing_ok=True) if remove else None,
    )


def _temp(suffix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix="moneymap-backup-", suffix=suffix)
    os.close(fd)
    return Path(name)


# ---------------------------------------------------------------- your data


@router.get("/download")
def download_mine(user: Login = Depends(current_user)) -> FileResponse:
    path = write_user_backup(user.id, user.username, _temp(".zip"))
    return _download(path, f"moneymap-{user.username}-{stamp()}.zip", remove=True)


@router.get("/files", response_model=list[BackupFile])
def my_files(user: Login = Depends(current_user)) -> list[BackupFile]:
    return _list(backups_dir(user.id), "user")


@router.get("/files/{name}")
def download_file(name: str, user: Login = Depends(current_user)) -> FileResponse:
    return _download(_file(backups_dir(user.id), name), name, remove=False)


@router.delete("/files/{name}", status_code=204)
def delete_file(name: str, user: Login = Depends(current_user)) -> None:
    _file(backups_dir(user.id), name).unlink()


@router.post("/upload", response_model=BackupFile, status_code=201)
async def upload_mine(request: Request, filename: str = "", user: Login = Depends(current_user)) -> BackupFile:
    suffix = ".db" if filename.lower().endswith(".db") else ".zip"
    dest = backups_dir(user.id) / f"uploaded-{stamp()}-{secrets.token_hex(3)}{suffix}"
    await _receive(request, dest)
    info = _info(dest, "user")
    if info.problem or info.kind != "user":
        dest.unlink(missing_ok=True)
        raise _bad(info.problem or "That is a whole-server backup — an admin restores it under Whole server.")
    return info


@router.post("/restore", response_model=RestoreOut)
def restore_mine(body: RestoreIn, user: Login = Depends(current_user)) -> RestoreOut:
    _check_password(user, body)
    path = _file(backups_dir(user.id), body.name)
    _no_fetch_running()
    try:
        saved = restore_user(user.id, user.username, path)
    except BackupError as e:
        raise _bad(str(e)) from None
    return RestoreOut(restored=path.name, saved_first=saved.name)


# ---------------------------------------------------------------- the whole server (admins)


@router.get("/server/download")
def download_server(_: Login = Depends(admin)) -> FileResponse:
    path = write_server_backup(_temp(".zip"))
    return _download(path, f"moneymap-server-{stamp()}.zip", remove=True)


@router.get("/server/files", response_model=list[BackupFile])
def server_files(_: Login = Depends(admin)) -> list[BackupFile]:
    return _list(server_backups_dir(), "server")


@router.get("/server/files/{name}")
def download_server_file(name: str, _: Login = Depends(admin)) -> FileResponse:
    return _download(_file(server_backups_dir(), name), name, remove=False)


@router.delete("/server/files/{name}", status_code=204)
def delete_server_file(name: str, _: Login = Depends(admin)) -> None:
    _file(server_backups_dir(), name).unlink()


@router.post("/server/upload", response_model=BackupFile, status_code=201)
async def upload_server(request: Request, _: Login = Depends(admin)) -> BackupFile:
    dest = server_backups_dir() / f"uploaded-{stamp()}-{secrets.token_hex(3)}.zip"
    await _receive(request, dest)
    info = _info(dest, "server")
    if info.problem or info.kind != "server":
        dest.unlink(missing_ok=True)
        raise _bad(info.problem or "That is one person's backup — restore it under Your data.")
    return info


@router.post("/server/restore", response_model=RestoreOut)
def restore_whole_server(body: RestoreIn, response: Response, me: Login = Depends(admin)) -> RestoreOut:
    _check_password(me, body)
    path = _file(server_backups_dir(), body.name)
    _no_fetch_running()
    try:
        saved = restore_server(path)
    except BackupError as e:
        raise _bad(str(e)) from None
    clear_session(response)  # the logins (and maybe the secret key) are the backup's now: sign in again
    return RestoreOut(restored=path.name, saved_first=saved.name, signed_out=True)

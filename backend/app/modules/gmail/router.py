from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_db
from ..auth.security import current_user
from . import client as gclient
from . import fetch as gfetch
from .models import GmailAccount, GmailRun
from .schemas import (
    GmailClientIn,
    GmailConnectIn,
    GmailConnectOut,
    GmailEstimateIn,
    GmailPasteIn,
    GmailProvider,
    GmailRunOut,
    GmailStartIn,
    GmailStatus,
)

router = APIRouter(prefix="/gmail", tags=["gmail"], dependencies=[Depends(current_user)])


def _bad(e: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e))


def _not_from_env() -> None:
    try:
        if gclient.env_client() is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The Google client is set on the server (MONEYMAP_GOOGLE_CLIENT_JSON) — change it there.",
            )
    except gclient.GmailError:
        pass  # set but unreadable: let a pasted client be used meanwhile


@router.get("/status", response_model=GmailStatus)
def gmail_status(db: Session = Depends(get_db)) -> GmailStatus:
    acct = gclient.account(db)
    env_error = None
    try:
        from_env = gclient.env_client() is not None
    except gclient.GmailError as e:
        from_env, env_error = False, f"MONEYMAP_GOOGLE_CLIENT_JSON: {e}"
    return GmailStatus(
        client_configured=acct is not None,
        client_from_env=from_env,
        client_env_error=env_error,
        client_id_hint=(acct.client_id[:12] + "…") if acct else None,
        connected=bool(acct and acct.token),
        email=acct.email if acct else None,
        connected_at=acct.connected_at.isoformat(timespec="seconds") if acct and acct.connected_at else None,
        last_fetch_to=acct.last_fetch_to if acct else None,
        consent_threshold_mb=gfetch.consent_threshold() // 1_000_000,
    )


@router.put("/client", response_model=GmailStatus)
def save_client(body: GmailClientIn, db: Session = Depends(get_db)) -> GmailStatus:
    """Store the user's own Google Cloud "Desktop app" OAuth client."""
    _not_from_env()
    try:
        cid, secret = gclient.parse_client_json(body.json_text)
    except gclient.GmailError as e:
        raise _bad(e) from None
    acct = gclient.account(db)
    if acct is None:
        db.add(GmailAccount(id=1, client_id=cid, client_secret=secret))
    else:
        if acct.client_id != cid:  # a different client invalidates the old token
            acct.token, acct.email, acct.connected_at = None, None, None
        acct.client_id, acct.client_secret = cid, secret
    db.commit()
    return gmail_status(db)


@router.delete("/client", response_model=GmailStatus)
def remove_client(db: Session = Depends(get_db)) -> GmailStatus:
    """Disconnect and forget the OAuth client. Fetched emails stay in the Inbox."""
    _not_from_env()
    gclient.disconnect(db)
    acct = gclient.account(db)
    if acct:
        db.delete(acct)
        db.commit()
    return gmail_status(db)


@router.post("/connect", response_model=GmailConnectOut)
def connect(body: GmailConnectIn, db: Session = Depends(get_db)) -> GmailConnectOut:
    try:
        return GmailConnectOut(**gclient.start_consent(db, body.origin))
    except gclient.GmailError as e:
        raise _bad(e) from None


@router.get("/callback", include_in_schema=False)
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Google redirects the browser here (loopback) after consent — back to the setup page
    when connecting from there."""
    from ..guide.service import setup_pending

    page = "/welcome?step=gmail&" if setup_pending(db) else "/settings?"
    if error:
        return RedirectResponse(f"{page}gmail=error&reason={error}", status_code=302)
    try:
        if not code or not state:
            raise gclient.GmailError("missing_code")
        gclient.finish_consent(db, code, state)
    except gclient.GmailError as e:
        from urllib.parse import quote

        return RedirectResponse(f"{page}gmail=error&reason={quote(str(e))}", status_code=302)
    return RedirectResponse(f"{page}gmail=connected", status_code=302)


@router.post("/callback-url", response_model=GmailStatus)
def paste_callback(body: GmailPasteIn, db: Session = Depends(get_db)) -> GmailStatus:
    """For browsers on another device: paste the URL Google redirected to."""
    try:
        code, state = gclient.code_from_url(body.url)
        gclient.finish_consent(db, code, state)
    except gclient.GmailError as e:
        raise _bad(e) from None
    return gmail_status(db)


@router.post("/disconnect", response_model=GmailStatus)
def disconnect(db: Session = Depends(get_db)) -> GmailStatus:
    gclient.disconnect(db)
    return gmail_status(db)


@router.get("/providers", response_model=list[GmailProvider])
def providers() -> list[dict]:
    """Bank/card statement and transaction-alert query templates from the India pack."""
    return gfetch.provider_options()


# ---------- runs ----------


def run_out(run: GmailRun) -> GmailRunOut:
    out = GmailRunOut.model_validate(run)
    out.bytes_human = gfetch.human_bytes(run.bytes_estimated)
    out.consent_required = run.bytes_estimated > gfetch.consent_threshold()
    return out


@router.post("/estimate", response_model=GmailRunOut)
def estimate(body: GmailEstimateIn, db: Session = Depends(get_db)) -> GmailRunOut:
    """Step 1: count matching emails and estimate download size. Downloads nothing."""
    try:
        return run_out(gfetch.estimate(db, body.template_ids, body.custom, body.date_from, body.date_to))
    except gclient.GmailError as e:
        raise _bad(e) from None


@router.post("/runs/{run_id}/start", response_model=GmailRunOut)
def start(run_id: int, body: GmailStartIn, db: Session = Depends(get_db)) -> GmailRunOut:
    """Step 2: download the new emails + attachments in the background."""
    run = _run(db, run_id)
    try:
        gfetch.start_fetch(db, run, body.consent)
    except gclient.GmailError as e:
        raise _bad(e) from None
    db.refresh(run)
    return run_out(run)


@router.get("/runs/{run_id}", response_model=GmailRunOut)
def get_run(run_id: int, db: Session = Depends(get_db)) -> GmailRunOut:
    return run_out(_run(db, run_id))


@router.post("/runs/{run_id}/cancel", response_model=GmailRunOut)
def cancel(run_id: int, db: Session = Depends(get_db)) -> GmailRunOut:
    run = _run(db, run_id)
    if run.status == "running":
        run.status = "cancelling"
    elif run.status == "estimated":
        run.status = "cancelled"
    db.commit()
    return run_out(run)


@router.get("/runs", response_model=list[GmailRunOut])
def list_runs(limit: int = Query(default=10, ge=1, le=50), db: Session = Depends(get_db)) -> list[GmailRunOut]:
    rows = db.scalars(select(GmailRun).where(GmailRun.status != "estimated").order_by(GmailRun.id.desc()).limit(limit))
    return [run_out(r) for r in rows]


def _run(db: Session, run_id: int) -> GmailRun:
    run = db.get(GmailRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fetch not found")
    return run

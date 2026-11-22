"""OAuth (user-owned Desktop client, PKCE, loopback redirect) + Gmail REST calls."""

import base64
import contextlib
import hashlib
import json
import secrets
import time
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from sqlalchemy.orm import Session

from ...core.crypto import DecryptError
from ..auth.models import Setting
from .models import GmailAccount

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
CALLBACK_PATH = "/api/gmail/callback"
STATE_KEY = "gmail_oauth_state"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


class GmailError(Exception):
    pass


# ---------------------------------------------------------------- client JSON


def parse_client_json(text: str) -> tuple[str, str]:
    """Accept Google's downloaded Desktop client JSON ({"installed": {...}})."""
    try:
        raw = json.loads(text)
    except ValueError:
        raise GmailError("That isn't valid JSON. Paste the whole contents of the downloaded client file.") from None
    if not isinstance(raw, dict):
        raise GmailError("That isn't an OAuth client JSON file.")
    if "web" in raw and "installed" not in raw:
        raise GmailError('This is a "Web application" client. Create a "Desktop app" OAuth client instead.')
    node = raw.get("installed", raw)
    cid, secret = node.get("client_id"), node.get("client_secret")
    if not cid or not secret:
        raise GmailError('Missing client_id / client_secret — download the JSON of a "Desktop app" OAuth client.')
    return cid, secret


def env_client() -> tuple[str, str] | None:
    """The OAuth client from MONEYMAP_GOOGLE_CLIENT_JSON (or _ID + _SECRET); None when not set.
    Raises GmailError when it's set but can't be read."""
    from ...config import get_settings

    s = get_settings()
    if s.google_client_json and s.google_client_json.strip():
        return parse_client_json(s.google_client_json.strip())
    if s.google_client_id or s.google_client_secret:
        if not (s.google_client_id and s.google_client_secret):
            raise GmailError("Set both MONEYMAP_GOOGLE_CLIENT_ID and MONEYMAP_GOOGLE_CLIENT_SECRET.")
        return s.google_client_id.strip(), s.google_client_secret.strip()
    return None


def account(db: Session) -> GmailAccount | None:
    """The Gmail row. With the client in the environment it's kept in step with it: a different
    client id drops the old connection (its token belongs to the other client)."""
    acct = db.get(GmailAccount, 1)
    try:
        env = env_client()
    except GmailError:
        return acct  # shown on the status; the saved client (if any) keeps working meanwhile
    if env is None:
        return acct
    cid, secret = env
    if acct is None:
        acct = GmailAccount(id=1, client_id=cid, client_secret=secret)
        db.add(acct)
        db.commit()
        return acct
    try:
        same_secret = acct.client_secret == secret
    except DecryptError:
        same_secret = False
    if acct.client_id != cid or not same_secret:
        if acct.client_id != cid:
            acct.token, acct.email, acct.connected_at = None, None, None
        acct.client_id, acct.client_secret = cid, secret
        db.commit()
    return acct


# ---------------------------------------------------------------- consent flow


def redirect_uri_for(origin: str) -> tuple[str, bool]:
    """Loopback redirect for Google's Desktop flow. Returns (uri, direct) —
    direct=False means the browser isn't on the server's machine, so Google's
    redirect will fail to load and the user pastes the URL back instead."""
    u = urlparse(origin)
    port = u.port or (443 if u.scheme == "https" else 80)
    host = u.hostname or "127.0.0.1"
    direct = host in LOOPBACK_HOSTS and u.scheme == "http"
    loop_host = "localhost" if host == "localhost" else "127.0.0.1"
    return f"http://{loop_host}:{port}{CALLBACK_PATH}", direct


def start_consent(db: Session, origin: str) -> dict:
    acct = account(db)
    if acct is None:
        raise GmailError("Add your OAuth client first.")
    redirect_uri, direct = redirect_uri_for(origin)
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    row = db.get(Setting, STATE_KEY) or Setting(key=STATE_KEY, value="")
    row.value = json.dumps({"state": state, "verifier": verifier, "redirect_uri": redirect_uri, "at": time.time()})
    db.merge(row)
    db.commit()
    params = {
        "client_id": acct.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return {"url": f"{AUTH_URL}?{urlencode(params)}", "redirect_uri": redirect_uri, "direct": direct}


def code_from_url(pasted: str) -> tuple[str, str]:
    """Pull code + state out of the URL Google redirected to."""
    q = parse_qs(urlparse(pasted.strip()).query)
    if q.get("error"):
        raise GmailError(f"Google returned an error: {q['error'][0]}")
    code, state = q.get("code", [None])[0], q.get("state", [None])[0]
    if not code or not state:
        raise GmailError("That URL has no ?code=…&state=… — copy the full address from the page Google sent you to.")
    return code, state


def http_post(url: str, data: dict) -> dict:
    """POST form data (overridden in tests)."""
    r = httpx.post(url, data=data, timeout=20)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400:
        raise GmailError(body.get("error_description") or body.get("error") or f"Google returned HTTP {r.status_code}")
    return body


def finish_consent(db: Session, code: str, state: str) -> str | None:
    row = db.get(Setting, STATE_KEY)
    saved = json.loads(row.value) if row else None
    if not saved or saved["state"] != state:
        raise GmailError("This sign-in link has expired or doesn't match. Click Connect Gmail again.")
    if time.time() - saved["at"] > 900:
        raise GmailError("The sign-in took longer than 15 minutes. Click Connect Gmail again.")
    acct = account(db)
    if acct is None:
        raise GmailError("Add your OAuth client first.")
    try:
        client_secret = acct.client_secret
    except DecryptError:
        raise GmailError("The saved OAuth client can't be read any more. Paste the client JSON again.") from None
    tok = http_post(
        TOKEN_URL,
        {
            "code": code,
            "client_id": acct.client_id,
            "client_secret": client_secret,
            "redirect_uri": saved["redirect_uri"],
            "grant_type": "authorization_code",
            "code_verifier": saved["verifier"],
        },
    )
    if SCOPE not in tok.get("scope", SCOPE):
        raise GmailError("Gmail read access wasn't granted. Tick the Gmail permission on Google's consent screen.")
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600))
    acct.token = tok
    acct.connected_at = datetime.now()
    db.delete(row)
    db.commit()
    try:
        acct.email = api_for(db).profile().get("emailAddress")
        db.commit()
    except GmailError:
        pass
    return acct.email


def disconnect(db: Session) -> None:
    acct = account(db)
    if acct and acct.token:
        tok = acct.token
        with contextlib.suppress(httpx.HTTPError):  # best effort: revoke at Google too
            httpx.post(REVOKE_URL, data={"token": tok.get("refresh_token") or tok.get("access_token")}, timeout=10)
        acct.token = None
        acct.email = None
        acct.connected_at = None
        db.commit()


# ---------------------------------------------------------------- API


class GmailAPI:
    """Thin read-only Gmail REST client with token refresh."""

    def __init__(self, db: Session):
        self.db = db
        acct = account(db)
        if acct is None or not acct.token:
            raise GmailError("Gmail isn't connected. Connect it in Settings.")
        self.acct = acct
        self.http = httpx.Client(timeout=30)

    def _client_secret(self) -> str:
        try:
            return self.acct.client_secret
        except DecryptError:
            raise GmailError("The saved OAuth client can't be read any more. Paste the client JSON again.") from None

    def _token(self) -> str:
        tok = dict(self.acct.token or {})
        if tok.get("expires_at", 0) - 60 < time.time():
            if not tok.get("refresh_token"):
                raise GmailError("Gmail access expired. Reconnect Gmail in Settings.")
            fresh = http_post(
                TOKEN_URL,
                {
                    "client_id": self.acct.client_id,
                    "client_secret": self._client_secret(),
                    "refresh_token": tok["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
            tok.update(fresh)
            tok["expires_at"] = time.time() + int(fresh.get("expires_in", 3600))
            self.acct.token = tok
            self.db.commit()
        return tok["access_token"]

    def _get(self, path: str, params: dict | None = None) -> dict:
        r = self.http.get(f"{API}{path}", params=params, headers={"Authorization": f"Bearer {self._token()}"})
        if r.status_code == 401:
            raise GmailError("Google rejected the Gmail token. Reconnect Gmail in Settings.")
        if r.status_code >= 400:
            try:
                msg = r.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                msg = f"HTTP {r.status_code}"
            raise GmailError(f"Gmail API error: {msg}")
        return r.json()

    def profile(self) -> dict:
        return self._get("/profile")

    def list_ids(self, q: str) -> list[str]:
        ids: list[str] = []
        token = None
        while True:
            params = {"q": q, "maxResults": 500}
            if token:
                params["pageToken"] = token
            data = self._get("/messages", params)
            ids += [m["id"] for m in data.get("messages", [])]
            token = data.get("nextPageToken")
            if not token:
                return ids

    def get_message(self, mid: str, fmt: str = "full") -> dict:
        return self._get(f"/messages/{mid}", {"format": fmt})

    def get_attachment(self, mid: str, aid: str) -> bytes:
        data = self._get(f"/messages/{mid}/attachments/{aid}")
        return base64.urlsafe_b64decode(data["data"] + "=" * (-len(data["data"]) % 4))


def api_for(db: Session) -> GmailAPI:
    """Factory (tests replace this with a fake)."""
    return GmailAPI(db)

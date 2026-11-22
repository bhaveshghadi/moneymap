"""Runtime settings, read from MONEYMAP_* environment variables."""

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MONEYMAP_")

    # Everything persistent (SQLite DB, secret key, later uploads) lives here.
    # In Docker this is the named volume mounted at /data.
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    # Signs session cookies. If unset, one is generated once and stored in
    # <data_dir>/secret_key so sessions survive restarts.
    secret_key: str | None = None
    session_days: int = 30
    # Set true when served over HTTPS (e.g. behind host nginx with TLS).
    cookie_secure: bool = False
    # Login lockout: this many wrong passwords in a row locks login for lockout_minutes.
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    # Gmail fetches estimated above this size need a confirmation tick.
    gmail_consent_mb: int = 1000
    # Download mutual fund prices (NAVs) from AMFI once a day. Off in test containers.
    nav_update: bool = True
    # Gmail: your Google "Desktop app" OAuth client, kept out of the database. Either the downloaded JSON
    # (one line) or the id and secret. When set, Settings doesn't ask for it.
    google_client_json: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'moneymap.db'}"

    def resolved_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        path = self.data_dir / "secret_key"
        if path.exists():
            return path.read_text().strip()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(48)
        path.write_text(key)
        return key


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s

"""Latest mutual fund prices (NAVs) from AMFI's public daily file. Nothing about you is sent.

https://www.amfiindia.com/spages/NAVAll.txt — lines like (current format, 8 columns)
    Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date
    122639;INF879O01027;-;Some Flexi Cap Fund;Direct Plan;Growth;93.9884;09-Nov-2026
or the older 6-column form without Plan / Option. NAV and date are always the last two
columns. Funds are matched by ISIN. A copy is kept in <data>/amfi/NAVAll.txt.
"""

import json
import logging
import threading
import time
from datetime import date, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ..auth.models import Setting
from .models import Fund

log = logging.getLogger("moneymap.nav")
AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
STATUS_KEY = "invest.nav_status"


def _row(line: str) -> tuple[list[str], str] | None:
    """Split a scheme line; returns (columns, display name incl. plan / option)."""
    parts = [p.strip() for p in line.split(";")]
    if len(parts) < 6 or not parts[0].isdigit():
        return None
    name = parts[3]
    if len(parts) >= 8:
        extra = [x for x in (parts[4], parts[5]) if x and x != "-"]
        if extra:
            name = f"{name} - {' - '.join(extra)}"
    return parts, name


def _nav(parts: list[str]) -> tuple[int, date] | None:
    try:
        return round(float(parts[-2]) * 10_000), datetime.strptime(parts[-1], "%d-%b-%Y").date()
    except ValueError:
        return None  # "N.A." NAVs, odd dates


def parse_navall(text: str) -> dict[str, tuple[str, int, date]]:
    """ISIN -> (AMFI scheme code, NAV in 1/10000 ₹, NAV date)."""
    out: dict[str, tuple[str, int, date]] = {}
    for line in text.splitlines():
        row = _row(line)
        if row is None:
            continue
        parts = row[0]
        nd = _nav(parts)
        if nd is None:
            continue
        for isin in (parts[1], parts[2]):
            if len(isin) == 12 and isin.startswith("IN"):
                out[isin] = (parts[0], nd[0], nd[1])
    return out


def fetch_navall(timeout: float = 30.0) -> str:
    r = httpx.get(AMFI_URL, timeout=timeout, follow_redirects=True, headers={"User-Agent": "moneymap-selfhosted/1.0"})
    r.raise_for_status()
    return r.text


def _cache_path() -> Path:
    d = get_settings().data_dir / "amfi"
    d.mkdir(parents=True, exist_ok=True)
    return d / "NAVAll.txt"


def amfi_text(max_age_hours: float = 20) -> str:
    """AMFI's file, fetched again once it's older than `max_age_hours`; the older copy
    is used if AMFI can't be reached."""
    path = _cache_path()
    if path.exists() and time.time() - path.stat().st_mtime < max_age_hours * 3600:
        return path.read_text(encoding="utf8", errors="replace")
    try:
        text = fetch_navall()
        path.write_text(text, encoding="utf8")
        return text
    except Exception:
        if path.exists():
            log.warning("AMFI unreachable — using the copy from %s", datetime.fromtimestamp(path.stat().st_mtime))
            return path.read_text(encoding="utf8", errors="replace")
        raise


def parse_schemes(text: str) -> list[dict]:
    """Every scheme in the AMFI file with its fund house (the "… Mutual Fund" line above it)."""
    out, amc = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ";" not in line:
            if line.lower().endswith("mutual fund"):
                amc = line
            continue
        row = _row(line)
        if row is None:
            continue
        parts, name = row
        nav, d = _nav(parts) or (None, None)
        isin = next((x for x in (parts[1], parts[2]) if len(x) == 12 and x.startswith("IN")), None)
        out.append({"code": parts[0], "isin": isin, "name": name, "amc": amc, "nav": nav, "nav_date": d})
    return out


_schemes: tuple[float, list[dict]] | None = None


def search_schemes(q: str, limit: int = 20, text: str | None = None) -> list[dict]:
    """Schemes whose name has every word typed (Direct / Growth first)."""
    global _schemes
    if text is not None:
        schemes = parse_schemes(text)
    else:
        raw = amfi_text()
        mtime = _cache_path().stat().st_mtime if _cache_path().exists() else time.time()
        if _schemes is None or _schemes[0] != mtime:
            _schemes = (mtime, parse_schemes(raw))
        schemes = _schemes[1]
    words = [w for w in q.lower().split() if w]
    if not words:
        return []
    hits = [s for s in schemes if s["isin"] and all(w in s["name"].lower() for w in words)]

    def rank(s: dict) -> tuple:
        n = s["name"].lower()
        return (not n.startswith(words[0]), "direct" not in n, "growth" not in n, len(n))

    return sorted(hits, key=rank)[:limit]


# ---------------------------------------------------------------- status + daily run


def get_status(db: Session) -> dict:
    row = db.get(Setting, STATUS_KEY)
    try:
        return json.loads(row.value) if row else {}
    except ValueError:
        return {}


def _set_status(db: Session, status: dict) -> None:
    row = db.get(Setting, STATUS_KEY)
    if row is None:
        db.add(Setting(key=STATUS_KEY, value=json.dumps(status)))
    else:
        row.value = json.dumps(status)
    db.commit()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def update_navs(db: Session, text: str | None = None) -> dict:
    """Set each fund's NAV from AMFI (a NAV only ever moves forward in time)."""
    funds = list(db.scalars(select(Fund).where(Fund.isin.is_not(None))))
    status: dict = {"last_run": _now(), "updated": 0, "funds": len(funds), "error": None, "not_found": []}
    if not funds:
        _set_status(db, status)
        return status
    try:
        navs = parse_navall(text if text is not None else amfi_text(max_age_hours=6))
    except Exception as e:  # network down, AMFI changed the file …
        log.warning("NAV update failed: %s", e)
        status["error"] = "Couldn't get prices from AMFI. The last prices are kept."
        _set_status(db, status)
        return status
    for f in funds:
        hit = navs.get(f.isin or "")
        if hit is None:
            status["not_found"].append(f.scheme)
            continue
        code, nav, d = hit
        f.amfi_code = code
        if f.nav_date is None or d >= f.nav_date:
            f.nav, f.nav_date, f.nav_source = nav, d, "amfi"
            status["updated"] += 1
    status["not_found"] = status["not_found"][:20]
    db.commit()
    _set_status(db, status)
    log.info("NAV update: %d of %d funds", status["updated"], len(funds))
    return status


def due(db: Session, now: datetime | None = None) -> bool:
    """Once a day after 9 pm (AMFI has published by then), or to catch up after 2 days off."""
    now = now or datetime.now()
    try:
        last = date.fromisoformat((get_status(db).get("last_run") or "")[:10])
    except ValueError:
        return True
    return (last < now.date() and now.hour >= 21) or (now.date() - last).days >= 2


def start_daily_updates() -> threading.Event | None:
    """A background thread that checks every hour whether today's NAVs are due."""
    if not get_settings().nav_update:
        return None
    from ...db import SessionLocal

    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(60):  # first check a minute after start, then hourly
            try:
                with SessionLocal() as db:
                    if db.scalar(select(Fund.account_id).limit(1)) is not None and due(db):
                        update_navs(db)
            except Exception:
                log.exception("NAV update crashed")
            stop.wait(3600 - 60)

    threading.Thread(target=loop, name="nav-update", daemon=True).start()
    return stop

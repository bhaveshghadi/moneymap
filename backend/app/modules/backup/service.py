"""Backups: a person's own (their database + uploaded PDFs + Gmail files) and the whole server's
(every person, the logins and the secret key — admins only).

Files are .zip with a manifest.json. A person's restore also takes a plain moneymap .db (the
automatic copies made before a reset). Before any restore the current data is saved first, so a
restore can itself be undone. Zip members are checked one by one: nothing is written outside the
expected places."""

import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from alembic.script import ScriptDirectory

from ...config import APP_VERSION, get_settings
from ...core.migrate import alembic_config, head, migrate_all, migrate_user
from ...core.users import dispose_users_engine, users_db_path
from ...db import dispose_all, dispose_engine, user_db_path, user_root

MAX_UPLOAD = 2 * 1024**3  # 2 GB
NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}\.(db|zip)$")
FOLDERS = ("uploads", "gmail")  # a person's files that go with their database
SAFE_FILE = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


class BackupError(Exception):
    pass


@dataclass
class Summary:
    kind: str  # user | server
    created: str | None
    username: str | None
    revision: str | None
    transactions: int | None = None
    accounts: int | None = None
    last_date: str | None = None
    people: int | None = None  # server backups


def stamp() -> str:
    return f"{datetime.now():%Y-%m-%d-%H%M%S}"


# ---------------------------------------------------------------- checks


def _copy_db(src: Path, dest: Path) -> None:
    """A consistent copy of a live SQLite file (its WAL included)."""
    s = sqlite3.connect(src)
    d = sqlite3.connect(dest)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def _known_revision(rev: str | None) -> bool:
    if not rev:
        return False
    try:
        return ScriptDirectory.from_config(alembic_config(Path("unused.db"))).get_revision(rev) is not None
    except Exception:
        return False


def check_db(path: Path) -> Summary:
    """A MoneyMap database we can open and upgrade."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise BackupError("That file isn't a database MoneyMap can read.") from e
    try:
        try:
            if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise BackupError("The database in the backup is damaged.")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.DatabaseError as e:
            raise BackupError("That file isn't a database MoneyMap can read.") from e
        if not {"alembic_version", "account", "transaction"} <= tables:
            raise BackupError("That database isn't a MoneyMap backup.")
        rev = (con.execute("SELECT version_num FROM alembic_version").fetchone() or [None])[0]
        if not _known_revision(rev):
            raise BackupError("That backup is from a newer MoneyMap. Update MoneyMap first, then restore it.")
        n_tx = con.execute('SELECT count(*), max(date) FROM "transaction"').fetchone()
        n_acc = con.execute("SELECT count(*) FROM account WHERE type IN ('asset','cash','credit_card')").fetchone()[0]
        return Summary("user", None, None, rev, n_tx[0], n_acc, n_tx[1])
    finally:
        con.close()


def _manifest(z: zipfile.ZipFile) -> dict:
    try:
        m = json.loads(z.read("manifest.json"))
    except (KeyError, ValueError) as e:
        raise BackupError("That zip isn't a MoneyMap backup (no manifest).") from e
    if m.get("app") != "moneymap" or m.get("kind") not in ("user", "server"):
        raise BackupError("That zip isn't a MoneyMap backup.")
    return m


def _safe_member(name: str) -> list[str] | None:
    parts = name.split("/")
    if name.startswith("/") or "\\" in name:
        return None
    if any(p in ("", ".", "..") for p in parts[:-1]) or parts[-1] in (".", ".."):
        return None
    return parts


def summarize(path: Path) -> Summary:
    """What a saved backup holds (for the list and the restore dialog)."""
    if path.suffix == ".db":
        s = check_db(path)
        s.created = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        return s
    try:
        with zipfile.ZipFile(path) as z:
            m = _manifest(z)
            if m["kind"] == "server":
                return Summary("server", m.get("created"), None, m.get("revision"), people=len(m.get("people", [])))
            with tempfile.TemporaryDirectory() as t:
                db = Path(t) / "moneymap.db"
                with z.open("moneymap.db") as src, open(db, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                s = check_db(db)
            s.created, s.username = m.get("created"), m.get("username")
            return s
    except zipfile.BadZipFile as e:
        raise BackupError("That file is damaged or not a zip.") from e
    except KeyError as e:
        raise BackupError("The backup has no database in it.") from e


# ---------------------------------------------------------------- a person's backup


def _add_folder(z: zipfile.ZipFile, folder: Path, arc: str) -> None:
    if folder.exists():
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                z.write(f, f"{arc}/{f.relative_to(folder).as_posix()}")


def write_user_backup(uid: int, username: str, dest: Path) -> Path:
    """dest: a .zip — manifest, moneymap.db and the uploads / gmail folders."""
    root = user_root(uid)
    with tempfile.TemporaryDirectory() as t:
        db = Path(t) / "moneymap.db"
        _copy_db(user_db_path(uid), db)
        manifest = {
            "app": "moneymap",
            "kind": "user",
            "version": APP_VERSION,
            "revision": head(),
            "created": datetime.now().isoformat(timespec="seconds"),
            "username": username,
        }
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
            z.write(db, "moneymap.db")
            for folder in FOLDERS:
                _add_folder(z, root / folder, folder)
    return dest


def restore_user(uid: int, username: str, path: Path) -> Path:
    """Replace this person's data with a saved backup. Returns the copy saved first."""
    root = user_root(uid)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        new_db = tmp / "moneymap.db"
        files: dict[str, Path] = {}
        if path.suffix == ".db":
            shutil.copyfile(path, new_db)
        else:
            try:
                with zipfile.ZipFile(path) as z:
                    if _manifest(z)["kind"] != "user":
                        raise BackupError("That is a whole-server backup — an admin restores it under Whole server.")
                    total = 0
                    for info in z.infolist():
                        parts = _safe_member(info.filename)
                        if parts is None or info.is_dir():
                            continue
                        total += info.file_size
                        if total > 4 * MAX_UPLOAD:
                            raise BackupError("That backup unpacks to more than MoneyMap allows.")
                        if parts == ["moneymap.db"]:
                            out = new_db
                        elif parts[0] in FOLDERS and all(SAFE_FILE.match(p) for p in parts[1:]) and len(parts) >= 2:
                            out = tmp / "files" / "/".join(parts)
                        else:
                            continue
                        out.parent.mkdir(parents=True, exist_ok=True)
                        with z.open(info) as src, open(out, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        if out != new_db:
                            files["/".join(parts)] = out
            except zipfile.BadZipFile as e:
                raise BackupError("That file is damaged or not a zip.") from e
            if not new_db.exists():
                raise BackupError("The backup has no database in it.")
        check_db(new_db)
        saved = backups_dir(uid) / f"moneymap-{stamp()}-before-restore.zip"
        write_user_backup(uid, username, saved)
        dispose_engine(uid)
        live = user_db_path(uid)
        for side in ("-wal", "-shm"):
            Path(f"{live}{side}").unlink(missing_ok=True)
        shutil.copyfile(new_db, live)
        if path.suffix == ".zip":  # the files come with it; a plain .db keeps today's files
            for folder in FOLDERS:
                shutil.rmtree(root / folder, ignore_errors=True)
            for rel, f in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(root / rel))
    migrate_user(uid)  # an older backup is brought up to date
    return saved


def backups_dir(uid: int) -> Path:
    d = user_root(uid) / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- the whole server (admins)


def server_backups_dir() -> Path:
    d = get_settings().data_dir / "server-backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _people() -> list[tuple[int, str]]:
    con = sqlite3.connect(users_db_path())
    try:
        return [(r[0], r[1]) for r in con.execute("SELECT id, username FROM login ORDER BY id")]
    finally:
        con.close()


def write_server_backup(dest: Path) -> Path:
    """Every person's database and files, the logins and the secret key (needed to read stored
    Gmail tokens and remembered passwords). People's own automatic backups are left out."""
    data = get_settings().data_dir
    people = _people()
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        manifest = {
            "app": "moneymap",
            "kind": "server",
            "version": APP_VERSION,
            "revision": head(),
            "created": datetime.now().isoformat(timespec="seconds"),
            "people": [u for _, u in people],
        }
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=2))
            _copy_db(users_db_path(), tmp / "users.db")
            z.write(tmp / "users.db", "users.db")
            key = data / "secret_key"
            if key.exists():
                z.write(key, "secret_key")
            for uid, _ in people:
                if user_db_path(uid).exists():
                    _copy_db(user_db_path(uid), tmp / f"{uid}.db")
                    z.write(tmp / f"{uid}.db", f"users/{uid}/moneymap.db")
                for folder in FOLDERS:
                    _add_folder(z, user_root(uid) / folder, f"users/{uid}/{folder}")
    return dest


def restore_server(path: Path) -> Path:
    """Replace every person, the logins and the secret key. The current server is saved first
    (as a server backup) and its files moved to replaced-<time>/ — nothing is deleted."""
    data = get_settings().data_dir
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t) / "new"
        tmp.mkdir()
        try:
            with zipfile.ZipFile(path) as z:
                if _manifest(z)["kind"] != "server":
                    raise BackupError("That is one person's backup — restore it under Your data.")
                total = 0
                for info in z.infolist():
                    parts = _safe_member(info.filename)
                    if parts is None or info.is_dir():
                        continue
                    total += info.file_size
                    if total > 8 * MAX_UPLOAD:
                        raise BackupError("That backup unpacks to more than MoneyMap allows.")
                    ok = parts in (["users.db"], ["secret_key"]) or (
                        len(parts) >= 3
                        and parts[0] == "users"
                        and parts[1].isdigit()
                        and (
                            parts[2:] == ["moneymap.db"]
                            or (parts[2] in FOLDERS and len(parts) >= 4 and all(SAFE_FILE.match(p) for p in parts[3:]))
                        )
                    )
                    if not ok:
                        continue
                    out = tmp / "/".join(parts)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        except zipfile.BadZipFile as e:
            raise BackupError("That file is damaged or not a zip.") from e
        if not (tmp / "users.db").exists():
            raise BackupError("The backup has no logins (users.db) in it.")
        con = sqlite3.connect(tmp / "users.db")
        try:
            admins = con.execute("SELECT count(*) FROM login WHERE is_admin = 1 AND disabled = 0").fetchone()[0]
        except sqlite3.Error as e:
            raise BackupError("The logins in that backup can't be read.") from e
        finally:
            con.close()
        if not admins:
            raise BackupError("That backup has no admin who can sign in.")
        for db in (tmp / "users").glob("*/moneymap.db"):
            check_db(db)
        saved = write_server_backup(server_backups_dir() / f"moneymap-server-{stamp()}-before-restore.zip")
        dispose_all()
        dispose_users_engine()
        aside = data / f"replaced-{stamp()}"
        aside.mkdir()
        for name in ("users.db", "users.db-wal", "users.db-shm", "users", "secret_key"):
            if (data / name).exists():
                shutil.move(str(data / name), str(aside / name))
        for item in tmp.iterdir():
            shutil.move(str(item), str(data / item.name))
    from ...core import crypto

    crypto._fernet.cache_clear()  # the secret key may be the backup's now
    migrate_all(lambda _m: None)
    return saved

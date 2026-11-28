"""Logins: making a person's data file ready."""

from ...core.migrate import migrate_user
from ...db import SessionLocal, as_user
from ..categories.seed import seed_categories
from .models import Setting


def prepare_user_data(uid: int) -> None:
    """A new person's database: the schema, the starter categories and the setup page to start with."""
    from ..guide.service import SETUP_KEY

    migrate_user(uid)
    with as_user(uid), SessionLocal() as db:
        seed_categories(db)
        if db.get(Setting, SETUP_KEY) is None:
            db.add(Setting(key=SETUP_KEY, value="pending"))  # a brand-new person: show the setup page first
        db.commit()

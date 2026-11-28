import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.db import Base

config = context.config
# Which database: given by app.core.migrate (one user's file), or MONEYMAP_ALEMBIC_URL for a manual run.
# Every user's file is upgraded at start-up with `python -m app.cli migrate`.
_url = config.attributes.get("url") or os.environ.get("MONEYMAP_ALEMBIC_URL")
if not _url:
    raise SystemExit(
        "Each user has their own database: run `python -m app.cli migrate`, "
        "or set MONEYMAP_ALEMBIC_URL=sqlite:///path/to/moneymap.db for one file."
    )
config.set_main_option("sqlalchemy.url", _url)

if config.config_file_name is not None and "url" not in config.attributes:
    fileConfig(config.config_file_name)  # not when run inside the app: it would reset the app's logging

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # render_as_batch: SQLite can't ALTER most things, so Alembic rebuilds tables
        # in batch mode. That needs every foreign key to have a NAME.
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

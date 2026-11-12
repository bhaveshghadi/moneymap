"""Admin CLI.  Usage:  python -m app.cli reset-password <username>"""

import typer
from sqlalchemy import select

from . import models  # noqa: F401  (registers every table)
from .db import SessionLocal
from .modules.auth.models import User
from .modules.auth.security import hash_password

cli = typer.Typer(no_args_is_help=True)


@cli.command("reset-password")
def reset_password(
    username: str,
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
) -> None:
    """Set a new password for USERNAME (signs out all sessions, clears a lockout)."""
    if len(password) < 8:
        raise typer.BadParameter("Password must be at least 8 characters")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            typer.echo(f"No user named {username!r}", err=True)
            raise typer.Exit(1)
        user.password_hash = hash_password(password)
        user.session_version += 1
        user.failed_logins = 0
        user.locked_until = None
        db.commit()
    typer.echo("Password updated.")


@cli.command("list-users")
def list_users() -> None:
    with SessionLocal() as db:
        for u in db.scalars(select(User)):
            typer.echo(u.username)


if __name__ == "__main__":
    cli()

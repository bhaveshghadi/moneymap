"""Admin CLI.  Usage:  python -m app.cli reset-password <username>
python -m app.cli list-users
python -m app.cli migrate        (start-up: every person's database)"""

import typer
from sqlalchemy import select

from . import models  # noqa: F401  (registers every table)
from .core.users import Login, users_session
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
    with users_session() as db:
        user = db.scalar(select(Login).where(Login.username == username))
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
    with users_session() as db:
        for u in db.scalars(select(Login).order_by(Login.id)):
            flags = [f for f, on in (("admin", u.is_admin), ("turned off", u.disabled)) if on]
            typer.echo(f"{u.id}  {u.username}" + (f"  ({', '.join(flags)})" if flags else ""))


@cli.command("migrate")
def migrate() -> None:
    """Move single-user data into users/<id>/ (once), then upgrade every person's database."""
    from .core.migrate import migrate_all

    migrate_all(typer.echo)


if __name__ == "__main__":
    cli()

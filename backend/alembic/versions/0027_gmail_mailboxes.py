"""Gmail: several connected accounts (mailboxes) under one Google client

The connection that was on gmail_account (token, email, connected date, last fetch) becomes
mailbox 1, and the emails already fetched are marked as coming from it.

Revision ID: 0027_gmail_mailboxes
Revises: 0026_loan_close
Create Date: 2026-11-28 18:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0027_gmail_mailboxes"
down_revision: Union[str, None] = "0026_loan_close"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gmail_mailbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("token_enc", sa.Text(), nullable=True),
        sa.Column("connected_at", sa.DateTime(), nullable=True),
        sa.Column("last_fetch_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    with op.batch_alter_table("gmail_message", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mailbox_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("rfc_id", sa.String(length=255), nullable=True))
        batch_op.create_foreign_key(
            "fk_gmail_message_mailbox_id_gmail_mailbox", "gmail_mailbox", ["mailbox_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_index("ix_gmail_message_mailbox_id", ["mailbox_id"])
        batch_op.create_index("ix_gmail_message_rfc_id", ["rfc_id"])
    with op.batch_alter_table("gmail_run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mailbox_ids", sa.JSON(), server_default="[]", nullable=False))

    # the one connection so far becomes mailbox 1; what it fetched came from it
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT token_enc, email, connected_at, last_fetch_to FROM gmail_account WHERE id = 1")
    ).first()
    had_mail = conn.execute(sa.text("SELECT 1 FROM gmail_message LIMIT 1")).first() is not None
    if row is not None and (row[0] or row[1] or had_mail):
        conn.execute(
            sa.text(
                "INSERT INTO gmail_mailbox (id, email, token_enc, connected_at, last_fetch_to) "
                "VALUES (1, :email, :token, :at, :last)"
            ),
            {"email": row[1], "token": row[0], "at": row[2], "last": row[3]},
        )
        conn.execute(sa.text("UPDATE gmail_message SET mailbox_id = 1"))
        conn.execute(sa.text("UPDATE gmail_run SET mailbox_ids = '[1]'"))

    with op.batch_alter_table("gmail_account", schema=None) as batch_op:
        batch_op.drop_column("token_enc")
        batch_op.drop_column("email")
        batch_op.drop_column("connected_at")
        batch_op.drop_column("last_fetch_to")


def downgrade() -> None:
    with op.batch_alter_table("gmail_account", schema=None) as batch_op:
        batch_op.add_column(sa.Column("token_enc", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("email", sa.String(length=320), nullable=True))
        batch_op.add_column(sa.Column("connected_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_fetch_to", sa.Date(), nullable=True))
    conn = op.get_bind()
    first = conn.execute(
        sa.text("SELECT token_enc, email, connected_at, last_fetch_to FROM gmail_mailbox ORDER BY id LIMIT 1")
    ).first()
    if first is not None:
        conn.execute(
            sa.text(
                "UPDATE gmail_account SET token_enc = :token, email = :email, connected_at = :at, "
                "last_fetch_to = :last WHERE id = 1"
            ),
            {"token": first[0], "email": first[1], "at": first[2], "last": first[3]},
        )
    with op.batch_alter_table("gmail_run", schema=None) as batch_op:
        batch_op.drop_column("mailbox_ids")
    with op.batch_alter_table("gmail_message", schema=None) as batch_op:
        batch_op.drop_index("ix_gmail_message_rfc_id")
        batch_op.drop_index("ix_gmail_message_mailbox_id")
        batch_op.drop_constraint("fk_gmail_message_mailbox_id_gmail_mailbox", type_="foreignkey")
        batch_op.drop_column("rfc_id")
        batch_op.drop_column("mailbox_id")
    op.drop_table("gmail_mailbox")

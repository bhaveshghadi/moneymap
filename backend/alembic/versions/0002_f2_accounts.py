"""F2 accounts: account table

Revision ID: 0002_f2_accounts
Revises: 0001_f1_auth
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_f2_accounts"
down_revision = "0001_f1_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("account_number", sa.String(length=64), nullable=True),
        sa.Column("opening_balance", sa.Integer(), nullable=False),
        sa.Column("opening_date", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("liability_kind", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("account") as batch:
        batch.create_index("ix_account_type", ["type"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("account") as batch:
        batch.drop_index("ix_account_type")
    op.drop_table("account")

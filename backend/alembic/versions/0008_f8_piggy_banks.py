"""F8 piggy banks: piggy_bank and piggy_event tables

Revision ID: 0008_f8_piggy_banks
Revises: 0007_f7_bills
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_f8_piggy_banks"
down_revision = "0007_f7_bills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "piggy_bank",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("target_amount", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["account.id"], name="fk_piggy_bank_account_id_account", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("piggy_bank") as batch:
        batch.create_index("ix_piggy_bank_account_id", ["account_id"], unique=False)
    op.create_table(
        "piggy_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("piggy_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["piggy_id"], ["piggy_bank.id"], name="fk_piggy_event_piggy_id_piggy_bank", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("piggy_event") as batch:
        batch.create_index("ix_piggy_event_piggy_id", ["piggy_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("piggy_event") as batch:
        batch.drop_index("ix_piggy_event_piggy_id")
    op.drop_table("piggy_event")
    with op.batch_alter_table("piggy_bank") as batch:
        batch.drop_index("ix_piggy_bank_account_id")
    op.drop_table("piggy_bank")

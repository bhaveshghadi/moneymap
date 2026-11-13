"""F7 bills: bill table, transaction.bill_id

Revision ID: 0007_f7_bills
Revises: 0006_f6_budgets
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_f7_bills"
down_revision = "0006_f6_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bill",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("amount_min", sa.Integer(), nullable=False),
        sa.Column("amount_max", sa.Integer(), nullable=False),
        sa.Column("first_due", sa.Date(), nullable=False),
        sa.Column("repeat", sa.String(length=16), nullable=False),
        sa.Column("skip", sa.Integer(), nullable=False),
        sa.Column("match", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    with op.batch_alter_table("transaction") as batch:
        batch.add_column(sa.Column("bill_id", sa.Integer(), nullable=True))
        batch.create_index("ix_transaction_bill_id", ["bill_id"], unique=False)
        batch.create_foreign_key("fk_transaction_bill_id_bill", "bill", ["bill_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("transaction") as batch:
        batch.drop_constraint("fk_transaction_bill_id_bill", type_="foreignkey")
        batch.drop_index("ix_transaction_bill_id")
        batch.drop_column("bill_id")
    op.drop_table("bill")

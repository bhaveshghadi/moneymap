"""F6 budgets: budget and budget_limit tables, transaction.budget_id

Revision ID: 0006_f6_budgets
Revises: 0005_f2_remove_liabilities
Create Date: 2026-11-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_f6_budgets"
down_revision = "0005_f2_remove_liabilities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "budget_limit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("budget_id", sa.Integer(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("auto_generated", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["budget_id"], ["budget.id"], name="fk_budget_limit_budget_id_budget", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("budget_id", "month", name="uq_budget_limit_budget_id_month"),
    )
    with op.batch_alter_table("budget_limit") as batch:
        batch.create_index("ix_budget_limit_budget_id", ["budget_id"], unique=False)
    with op.batch_alter_table("transaction") as batch:
        batch.add_column(sa.Column("budget_id", sa.Integer(), nullable=True))
        batch.create_index("ix_transaction_budget_id", ["budget_id"], unique=False)
        batch.create_foreign_key(
            "fk_transaction_budget_id_budget", "budget", ["budget_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("transaction") as batch:
        batch.drop_constraint("fk_transaction_budget_id_budget", type_="foreignkey")
        batch.drop_index("ix_transaction_budget_id")
        batch.drop_column("budget_id")
    with op.batch_alter_table("budget_limit") as batch:
        batch.drop_index("ix_budget_limit_budget_id")
    op.drop_table("budget_limit")
    op.drop_table("budget")

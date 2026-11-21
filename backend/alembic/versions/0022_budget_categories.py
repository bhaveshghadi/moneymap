"""Budgets: budget_category (categories a budget counts by itself)

Revision ID: 0022_budget_categories
Revises: 0021_cas_import_mode
Create Date: 2026-11-21 14:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0022_budget_categories"
down_revision: Union[str, None] = "0021_cas_import_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budget_category",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("budget_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["budget_id"], ["budget.id"], name="fk_budget_category_budget_id_budget", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["category.id"], name="fk_budget_category_category_id_category", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_id", name="uq_budget_category_category_id"),
    )
    with op.batch_alter_table("budget_category", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_budget_category_budget_id"), ["budget_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("budget_category", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_budget_category_budget_id"))
    op.drop_table("budget_category")

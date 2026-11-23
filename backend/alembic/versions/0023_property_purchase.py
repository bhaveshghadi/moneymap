"""Property bought in parts: property_deal, property_instalment, property_cost

Revision ID: 0023_property_purchase
Revises: 0022_budget_categories
Create Date: 2026-11-23 18:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023_property_purchase"
down_revision: Union[str, None] = "0022_budget_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "property_deal",
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=True),
        sa.Column("size", sa.String(length=60), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("survey_no", sa.String(length=60), nullable=True),
        sa.Column("seller", sa.String(length=120), nullable=True),
        sa.Column("agreement_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("registered_on", sa.Date(), nullable=True),
        sa.Column("goal_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], name="fk_property_deal_account_id_account", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["piggy_bank.id"], name="fk_property_deal_goal_id_piggy_bank", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("account_id"),
    )
    op.create_table(
        "property_instalment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["property_deal.account_id"], name="fk_property_instalment_account_id_property_deal", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("property_instalment", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_property_instalment_account_id"), ["account_id"], unique=False)
    op.create_table(
        "property_cost",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=120), nullable=True),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["property_deal.account_id"], name="fk_property_cost_account_id_property_deal", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transaction.id"], name="fk_property_cost_transaction_id_transaction", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("property_cost", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_property_cost_account_id"), ["account_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("property_cost", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_property_cost_account_id"))
    op.drop_table("property_cost")
    with op.batch_alter_table("property_instalment", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_property_instalment_account_id"))
    op.drop_table("property_instalment")
    op.drop_table("property_deal")

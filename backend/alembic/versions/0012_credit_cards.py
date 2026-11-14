"""Credit cards: credit_card and card_cycle_rule (cards are accounts of type credit_card)

Revision ID: 0012_credit_cards
Revises: 0011_statement_import
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_credit_cards"
down_revision = "0011_statement_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_card",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("bank", sa.String(length=80), nullable=True),
        sa.Column("last4", sa.String(length=4), nullable=True),
        sa.Column("network", sa.String(length=24), nullable=True),
        sa.Column("credit_limit", sa.Integer(), nullable=False),
        sa.Column("min_due_pct", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["account.id"], name="fk_credit_card_account_id_account", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", name="uq_credit_card_account_id"),
    )
    op.create_table(
        "card_cycle_rule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("statement_day", sa.Integer(), nullable=False),
        sa.Column("due_mode", sa.String(length=16), nullable=False),
        sa.Column("due_value", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["card_id"], ["credit_card.id"], name="fk_card_cycle_rule_card_id_credit_card", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_card_cycle_rule_card_id", "card_cycle_rule", ["card_id"])


def downgrade() -> None:
    op.drop_index("ix_card_cycle_rule_card_id", table_name="card_cycle_rule")
    op.drop_table("card_cycle_rule")
    op.drop_table("credit_card")

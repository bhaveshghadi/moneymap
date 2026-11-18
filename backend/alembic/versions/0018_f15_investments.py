"""Investments (by hand): investment table

Revision ID: 0018_f15_investments
Revises: 0017_loan_first_interest
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_f15_investments"
down_revision = "0017_loan_first_interest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("subtype", sa.String(length=16), nullable=True),
        sa.Column("institution", sa.String(length=120), nullable=True),
        sa.Column("number", sa.String(length=64), nullable=True),
        sa.Column("person", sa.String(length=120), nullable=True),
        sa.Column("rate_bp", sa.Integer(), nullable=True),
        sa.Column("compounding", sa.String(length=12), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("maturity_date", sa.Date(), nullable=True),
        sa.Column("months", sa.Integer(), nullable=True),
        sa.Column("instalment", sa.Integer(), nullable=True),
        sa.Column("frequency", sa.String(length=12), nullable=True),
        sa.Column("sum_assured", sa.Integer(), nullable=True),
        sa.Column("maturity_amount", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("purity", sa.String(length=8), nullable=True),
        sa.Column("unit_price", sa.Integer(), nullable=True),
        sa.Column("current_value", sa.Integer(), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("payout_on", sa.Date(), nullable=True),
        sa.Column("payout_amount", sa.Integer(), nullable=True),
        sa.Column("pay_from_id", sa.Integer(), nullable=True),
        sa.Column("closed_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["account.id"], name="fk_investment_account_id_account", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pay_from_id"], ["account.id"], name="fk_investment_pay_from_id_account", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", name="uq_investment_account_id"),
    )


def downgrade() -> None:
    op.drop_table("investment")

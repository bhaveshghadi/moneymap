"""Loans: first_interest — EMI 1's interest by days since the loan was paid out (365 / 360-day year)

Revision ID: 0017_loan_first_interest
Revises: 0016_loan_changes
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_loan_first_interest"
down_revision = "0016_loan_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("loan") as batch:
        batch.add_column(sa.Column("first_interest", sa.String(length=8), server_default="month", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("loan") as batch:
        batch.drop_column("first_interest")

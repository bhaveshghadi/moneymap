"""Loans: interest_basis (month | days365)

Revision ID: 0025_loan_interest_basis
Revises: 0024_gmail_found
Create Date: 2026-11-26 12:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0025_loan_interest_basis"
down_revision: Union[str, None] = "0024_gmail_found"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("loan", schema=None) as batch_op:
        batch_op.add_column(sa.Column("interest_basis", sa.String(length=8), server_default="month", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("loan", schema=None) as batch_op:
        batch_op.drop_column("interest_basis")

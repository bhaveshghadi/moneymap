"""Loans: closing a loan early — what to put back if the close is undone

Revision ID: 0026_loan_close
Revises: 0025_loan_interest_basis
Create Date: 2026-11-28 12:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0026_loan_close"
down_revision: Union[str, None] = "0025_loan_interest_basis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("loan_event", schema=None) as batch_op:
        batch_op.add_column(sa.Column("txn_was", sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column("paid_before_was", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("loan_event", schema=None) as batch_op:
        batch_op.drop_column("paid_before_was")
        batch_op.drop_column("txn_was")

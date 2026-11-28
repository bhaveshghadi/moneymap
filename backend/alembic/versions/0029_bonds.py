"""Bonds: issuer platform / rating / repayment style / face value, and payouts received

Revision ID: 0029_bonds
Revises: 0028_statement_keep_duplicate
Create Date: 2026-11-29 10:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0029_bonds"
down_revision: Union[str, None] = "0028_statement_keep_duplicate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("investment", schema=None) as batch_op:
        batch_op.add_column(sa.Column("platform", sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column("rating", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("repayment", sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column("face_value", sa.Integer(), nullable=True))
    op.create_table(
        "bond_payout",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=True),
        sa.Column("interest", sa.Integer(), nullable=False),
        sa.Column("principal", sa.Integer(), nullable=False),
        sa.Column("tds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("interest_txn_id", sa.Integer(), nullable=True),
        sa.Column("principal_txn_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["account.id"], name="fk_bond_payout_account_id_account", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["interest_txn_id"],
            ["transaction.id"],
            name="fk_bond_payout_interest_txn_id_transaction",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["principal_txn_id"],
            ["transaction.id"],
            name="fk_bond_payout_principal_txn_id_transaction",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("bond_payout", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_bond_payout_account_id"), ["account_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("bond_payout", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_bond_payout_account_id"))
    op.drop_table("bond_payout")
    with op.batch_alter_table("investment", schema=None) as batch_op:
        batch_op.drop_column("face_value")
        batch_op.drop_column("repayment")
        batch_op.drop_column("rating")
        batch_op.drop_column("platform")

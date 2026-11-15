"""Loans phase 2: loan_event (part-payments, rate changes), statement_row.loan_id / loan_action

Revision ID: 0016_loan_changes
Revises: 0015_loans
Create Date: 2026-11-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_loan_changes"
down_revision = "0015_loans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "loan_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("loan_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("rate_bp", sa.Integer(), nullable=True),
        sa.Column("txn_id", sa.Integer(), nullable=True),
        sa.Column("txn_created", sa.Boolean(), nullable=False),
        sa.Column("fee_txn_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["loan_id"], ["loan.id"], name="fk_loan_event_loan_id_loan", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["txn_id"], ["transaction.id"], name="fk_loan_event_txn_id_transaction", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["fee_txn_id"], ["transaction.id"], name="fk_loan_event_fee_txn_id_transaction", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_loan_event_loan_id", "loan_event", ["loan_id"])
    with op.batch_alter_table("statement_row") as batch:
        batch.add_column(sa.Column("loan_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("loan_action", sa.String(length=8), nullable=True))
        batch.create_foreign_key("fk_statement_row_loan_id_loan", "loan", ["loan_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("statement_row") as batch:
        batch.drop_constraint("fk_statement_row_loan_id_loan", type_="foreignkey")
        batch.drop_column("loan_action")
        batch.drop_column("loan_id")
    op.drop_index("ix_loan_event_loan_id", table_name="loan_event")
    op.drop_table("loan_event")

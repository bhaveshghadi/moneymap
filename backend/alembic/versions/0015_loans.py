"""Loans: loan table, transaction.loan_id / loan_part, Loan Interest category

Revision ID: 0015_loans
Revises: 0014_card_emis
Create Date: 2026-11-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_loans"
down_revision = "0014_card_emis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "loan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("lender", sa.String(length=120), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("loan_number", sa.String(length=32), nullable=True),
        sa.Column("method", sa.String(length=12), nullable=False),
        sa.Column("count_mode", sa.String(length=16), nullable=False),
        sa.Column("principal", sa.Integer(), nullable=True),
        sa.Column("rate_bp", sa.Integer(), nullable=True),
        sa.Column("tenure", sa.Integer(), nullable=False),
        sa.Column("emi", sa.Integer(), nullable=False),
        sa.Column("first_emi_date", sa.Date(), nullable=False),
        sa.Column("disbursed_date", sa.Date(), nullable=True),
        sa.Column("pay_from_id", sa.Integer(), nullable=True),
        sa.Column("paid_before", sa.Integer(), nullable=False),
        sa.Column("closed_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["account.id"], name="fk_loan_account_id_account", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["pay_from_id"], ["account.id"], name="fk_loan_pay_from_id_account", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", name="uq_loan_account_id"),
    )
    with op.batch_alter_table("transaction") as batch:
        batch.add_column(sa.Column("loan_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("loan_part", sa.String(length=12), nullable=True))
        batch.add_column(sa.Column("loan_n", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_transaction_loan_id_loan", "loan", ["loan_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_transaction_loan_id", ["loan_id"])
    conn = op.get_bind()
    has_any = conn.execute(sa.text("SELECT COUNT(*) FROM category")).scalar()
    exists = conn.execute(sa.text("SELECT COUNT(*) FROM category WHERE name = 'Loan Interest'")).scalar()
    if has_any and not exists:
        conn.execute(
            sa.text(
                "INSERT INTO category (name, kind, icon, color, essential) "
                "VALUES ('Loan Interest', 'expense', 'percent', 'coral', 0)"
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("transaction") as batch:
        batch.drop_index("ix_transaction_loan_id")
        batch.drop_constraint("fk_transaction_loan_id_loan", type_="foreignkey")
        batch.drop_column("loan_n")
        batch.drop_column("loan_part")
        batch.drop_column("loan_id")
    op.drop_table("loan")

"""Card EMIs: card_emi, transaction.emi_id, statement_row.emi_id

Revision ID: 0014_card_emis
Revises: 0013_card_statements
Create Date: 2026-11-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_card_emis"
down_revision = "0013_card_statements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "card_emi",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("principal", sa.Integer(), nullable=False),
        sa.Column("tenure", sa.Integer(), nullable=False),
        sa.Column("instalment", sa.Integer(), nullable=True),
        sa.Column("interest_rate_bp", sa.Integer(), nullable=True),
        sa.Column("processing_fee", sa.Integer(), nullable=True),
        sa.Column("no_cost", sa.Boolean(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("paid_before", sa.Integer(), nullable=False),
        sa.Column("created_txn_id", sa.Integer(), nullable=True),
        sa.Column("purchase_txn_id", sa.Integer(), nullable=True),
        sa.Column("closed_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["card_id"], ["credit_card.id"], name="fk_card_emi_card_id_credit_card", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["account.id"], name="fk_card_emi_account_id_account", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_txn_id"], ["transaction.id"], name="fk_card_emi_created_txn_id_transaction", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["purchase_txn_id"], ["transaction.id"], name="fk_card_emi_purchase_txn_id_transaction", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", name="uq_card_emi_account_id"),
    )
    op.create_index("ix_card_emi_card_id", "card_emi", ["card_id"])
    with op.batch_alter_table("transaction") as batch:
        batch.add_column(sa.Column("emi_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_transaction_emi_id_card_emi", "card_emi", ["emi_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_transaction_emi_id", ["emi_id"])
    with op.batch_alter_table("statement_row") as batch:
        batch.add_column(sa.Column("emi_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_statement_row_emi_id_card_emi", "card_emi", ["emi_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("statement_row") as batch:
        batch.drop_constraint("fk_statement_row_emi_id_card_emi", type_="foreignkey")
        batch.drop_column("emi_id")
    with op.batch_alter_table("transaction") as batch:
        batch.drop_index("ix_transaction_emi_id")
        batch.drop_constraint("fk_transaction_emi_id_card_emi", type_="foreignkey")
        batch.drop_column("emi_id")
    op.drop_index("ix_card_emi_card_id", table_name="card_emi")
    op.drop_table("card_emi")

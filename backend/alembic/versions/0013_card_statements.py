"""Card statement import: statement summary figures, payment links, EMI flag, Card Fees & Interest category

Revision ID: 0013_card_statements
Revises: 0012_credit_cards
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_card_statements"
down_revision = "0012_credit_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("statement_import") as batch:
        batch.add_column(sa.Column("statement_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("period_start", sa.Date(), nullable=True))
        batch.add_column(sa.Column("due_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("total_due", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("min_due", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("previous_balance", sa.Integer(), nullable=True))
    with op.batch_alter_table("statement_row") as batch:
        batch.add_column(sa.Column("link_txn_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("flag", sa.String(length=16), nullable=True))
        batch.create_foreign_key(
            "fk_statement_row_link_txn_id_transaction", "transaction", ["link_txn_id"], ["id"], ondelete="SET NULL"
        )
    # The new starter category, for installs that already have their categories (only if
    # there are categories at all: a fresh install gets it from the seed on first run).
    conn = op.get_bind()
    has_any = conn.execute(sa.text("SELECT COUNT(*) FROM category")).scalar()
    exists = conn.execute(sa.text("SELECT COUNT(*) FROM category WHERE name = 'Card Fees & Interest'")).scalar()
    if has_any and not exists:
        conn.execute(
            sa.text(
                "INSERT INTO category (name, kind, icon, color, essential) "
                "VALUES ('Card Fees & Interest', 'expense', 'percent', 'red', 0)"
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("statement_row") as batch:
        batch.drop_constraint("fk_statement_row_link_txn_id_transaction", type_="foreignkey")
        batch.drop_column("flag")
        batch.drop_column("link_txn_id")
    with op.batch_alter_table("statement_import") as batch:
        for c in ("previous_balance", "min_due", "total_due", "due_date", "period_start", "statement_date"):
            batch.drop_column(c)

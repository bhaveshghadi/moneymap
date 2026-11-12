"""F4 transactions and transaction tags

Revision ID: 0004_f4_transactions
Revises: 0003_f3_categories_tags
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_f4_transactions"
down_revision = "0003_f3_categories_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transaction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("destination_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["account.id"], name="fk_transaction_source_id_account"),
        sa.ForeignKeyConstraint(["destination_id"], ["account.id"], name="fk_transaction_destination_id_account"),
        sa.ForeignKeyConstraint(
            ["category_id"], ["category.id"], name="fk_transaction_category_id_category", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("transaction") as batch:
        for col in ("type", "date", "source_id", "destination_id", "category_id"):
            batch.create_index(f"ix_transaction_{col}", [col], unique=False)
    op.create_table(
        "transaction_tag",
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transaction.id"],
            name="fk_transaction_tag_transaction_id_transaction", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"], name="fk_transaction_tag_tag_id_tag", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("transaction_id", "tag_id"),
    )


def downgrade() -> None:
    op.drop_table("transaction_tag")
    with op.batch_alter_table("transaction") as batch:
        for col in ("type", "date", "source_id", "destination_id", "category_id"):
            batch.drop_index(f"ix_transaction_{col}")
    op.drop_table("transaction")

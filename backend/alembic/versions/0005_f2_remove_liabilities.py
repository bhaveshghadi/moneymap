"""F2 change: no liability accounts in the first release (cards and loans become their own features)

Deletes liability accounts (refusing if any has transactions) and drops account.liability_kind.

Revision ID: 0005_f2_remove_liabilities
Revises: 0004_f4_transactions
Create Date: 2026-11-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_f2_remove_liabilities"
down_revision = "0004_f4_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    used = conn.execute(
        sa.text(
            'SELECT COUNT(*) FROM "transaction" t JOIN account a ON a.id IN (t.source_id, t.destination_id) '
            "WHERE a.type = 'liability'"
        )
    ).scalar()
    if used:
        raise RuntimeError(
            f"{used} transaction(s) use a liability account. Move or delete them before upgrading "
            "(liability accounts are not part of this release)."
        )
    conn.execute(sa.text("DELETE FROM account WHERE type = 'liability'"))
    with op.batch_alter_table("account") as batch:
        batch.drop_column("liability_kind")


def downgrade() -> None:
    # The deleted liability accounts can't be brought back; only the column returns.
    with op.batch_alter_table("account") as batch:
        batch.add_column(sa.Column("liability_kind", sa.String(length=8), nullable=True))

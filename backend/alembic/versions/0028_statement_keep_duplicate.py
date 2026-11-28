"""Statement rows: keep_duplicate (you ticked a row MoneyMap found already recorded)

Revision ID: 0028_statement_keep_duplicate
Revises: 0027_gmail_mailboxes
Create Date: 2026-11-28 20:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0028_statement_keep_duplicate"
down_revision: Union[str, None] = "0027_gmail_mailboxes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("statement_row", schema=None) as batch_op:
        batch_op.add_column(sa.Column("keep_duplicate", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("statement_row", schema=None) as batch_op:
        batch_op.drop_column("keep_duplicate")

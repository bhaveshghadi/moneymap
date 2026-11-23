"""Gmail runs: found (the emails found, to pick what to fetch)

Revision ID: 0024_gmail_found
Revises: 0023_property_purchase
Create Date: 2026-11-24 12:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0024_gmail_found"
down_revision: Union[str, None] = "0023_property_purchase"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("gmail_run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("found", sa.JSON(), server_default="[]", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("gmail_run", schema=None) as batch_op:
        batch_op.drop_column("found")

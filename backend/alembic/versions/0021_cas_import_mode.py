"""CAS review: cas_fund.mode (both | fund | txns)

Revision ID: 0021_cas_import_mode
Revises: 0020_f10_rules
Create Date: 2026-11-21 12:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021_cas_import_mode"
down_revision: Union[str, None] = "0020_f10_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cas_fund", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mode", sa.String(length=8), server_default="both", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("cas_fund", schema=None) as batch_op:
        batch_op.drop_column("mode")

"""Emergency fund: category.essential and the emergency_fund settings table

Revision ID: 0009_emergency_fund
Revises: 0008_f8_piggy_banks
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_emergency_fund"
down_revision = "0008_f8_piggy_banks"
branch_labels = None
depends_on = None

# Starter expense categories that count as essential (same list as app/modules/categories/seed.py,
# copied so this migration never changes when the app does).
ESSENTIAL = (
    "Rent",
    "Housing",
    "Society Maintenance",
    "Utilities",
    "Electricity",
    "Water",
    "Gas",
    "Mobile & Internet",
    "Groceries",
    "Transport",
    "Fuel",
    "Health",
    "Pharmacy",
    "Insurance",
    "Education & Fees",
    "Kids & Childcare",
    "Domestic Help",
    "Loan / EMI",
    "Family Support",
    "Taxes",
)


def upgrade() -> None:
    with op.batch_alter_table("category") as batch:
        batch.add_column(sa.Column("essential", sa.Boolean(), server_default="0", nullable=False))
    category = sa.table("category", sa.column("name", sa.String), sa.column("kind", sa.String),
                        sa.column("essential", sa.Boolean))
    op.execute(
        category.update()
        .where(category.c.name.in_(ESSENTIAL), category.c.kind == "expense")
        .values(essential=True)
    )
    op.create_table(
        "emergency_fund",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("piggy_id", sa.Integer(), nullable=True),
        sa.Column("months_cover", sa.Integer(), nullable=False),
        sa.Column("average_months", sa.Integer(), nullable=False),
        sa.Column("monthly_override", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(
            ["piggy_id"], ["piggy_bank.id"], name="fk_emergency_fund_piggy_id_piggy_bank", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("emergency_fund")
    with op.batch_alter_table("category") as batch:
        batch.drop_column("essential")

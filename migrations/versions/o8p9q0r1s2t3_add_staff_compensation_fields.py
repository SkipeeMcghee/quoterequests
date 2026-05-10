"""add staff compensation fields

Revision ID: o8p9q0r1s2t3
Revises: n7o8p9q0r1s2
Create Date: 2026-05-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "o8p9q0r1s2t3"
down_revision = "n7o8p9q0r1s2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("staff_members", sa.Column("compensation_amount", sa.Numeric(10, 2), nullable=True))
    op.add_column("staff_members", sa.Column("compensation_frequency", sa.String(length=24), nullable=True))


def downgrade() -> None:
    op.drop_column("staff_members", "compensation_frequency")
    op.drop_column("staff_members", "compensation_amount")
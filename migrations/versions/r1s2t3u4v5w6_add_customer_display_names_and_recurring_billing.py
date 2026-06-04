"""add customer display names and recurring billing

Revision ID: r1s2t3u4v5w6
Revises: q0r1s2t3u4v5
Create Date: 2026-06-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "r1s2t3u4v5w6"
down_revision = "q0r1s2t3u4v5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customers", sa.Column("individual_name", sa.String(length=255), nullable=True))
    op.add_column("customers", sa.Column("business_name", sa.String(length=255), nullable=True))
    op.add_column("customers", sa.Column("display_name_preference", sa.String(length=16), nullable=True))
    op.add_column("recurring_works", sa.Column("billing_amount", sa.Numeric(10, 2), nullable=True))
    op.add_column("recurring_works", sa.Column("billing_frequency", sa.String(length=16), nullable=True))

    op.execute(
        "UPDATE customers "
        "SET individual_name = primary_name, display_name_preference = 'individual' "
        "WHERE primary_name IS NOT NULL AND (individual_name IS NULL OR individual_name = '')"
    )


def downgrade():
    op.drop_column("recurring_works", "billing_frequency")
    op.drop_column("recurring_works", "billing_amount")
    op.drop_column("customers", "display_name_preference")
    op.drop_column("customers", "business_name")
    op.drop_column("customers", "individual_name")
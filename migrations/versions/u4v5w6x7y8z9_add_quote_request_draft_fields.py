"""add quote request draft fields

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-06-17 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "u4v5w6x7y8z9"
down_revision = "t3u4v5w6x7y8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("quote_requests", sa.Column("draft_quote_amount", sa.Numeric(10, 2), nullable=True))
    op.add_column("quote_requests", sa.Column("draft_quote_billing_frequency", sa.String(length=16), nullable=True))
    op.add_column("quote_requests", sa.Column("draft_quote_description", sa.String(length=255), nullable=True))
    op.add_column("quote_requests", sa.Column("draft_quote_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("quote_requests", "draft_quote_updated_at")
    op.drop_column("quote_requests", "draft_quote_description")
    op.drop_column("quote_requests", "draft_quote_billing_frequency")
    op.drop_column("quote_requests", "draft_quote_amount")

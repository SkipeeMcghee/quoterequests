"""add billing_frequency to request quotes

Revision ID: k4l5m6n7o8p9
Revises: j3k4l5m6n7o8
Create Date: 2026-05-09 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'k4l5m6n7o8p9'
down_revision = 'j3k4l5m6n7o8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'request_quotes',
        sa.Column('billing_frequency', sa.String(length=16), nullable=True),
    )


def downgrade():
    op.drop_column('request_quotes', 'billing_frequency')
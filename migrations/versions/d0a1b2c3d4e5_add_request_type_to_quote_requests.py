"""add request_type to quote_requests

Revision ID: d0a1b2c3d4e5
Revises: cc8fa3b4c295
Create Date: 2026-04-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd0a1b2c3d4e5'
down_revision = 'cc8fa3b4c295'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'quote_requests',
        sa.Column('request_type', sa.String(length=32), nullable=False, server_default='Quote request'),
    )
    op.alter_column('quote_requests', 'request_type', server_default=None)


def downgrade():
    op.drop_column('quote_requests', 'request_type')

"""add last_contacted_on to quote_requests

Revision ID: a2b3c4d5e6f7
Revises: cc8fa3b4c295
Create Date: 2026-04-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a2b3c4d5e6f7'
down_revision = 'd0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'quote_requests',
        sa.Column('last_contacted_on', sa.Date(), nullable=True),
    )


def downgrade():
    op.drop_column('quote_requests', 'last_contacted_on')

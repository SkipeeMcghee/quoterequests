"""add additional_notes to quote_requests

Revision ID: e1f2a3b4c5d6
Revises: a2b3c4d5e6f7
Create Date: 2026-04-27 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e1f2a3b4c5d6'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'quote_requests',
        sa.Column('additional_notes', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column('quote_requests', 'additional_notes')

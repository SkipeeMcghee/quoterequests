"""add recurrence config to recurring works

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-06-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "t3u4v5w6x7y8"
down_revision = "s2t3u4v5w6x7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("recurring_works", sa.Column("recurrence_config", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("recurring_works", "recurrence_config")
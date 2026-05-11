"""update request quote decisions to sent

Revision ID: m6n7o8p9q0r1
Revises: l5m6n7o8p9q0
Create Date: 2026-05-09 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'm6n7o8p9q0r1'
down_revision = 'l5m6n7o8p9q0'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    request_quotes = sa.table(
        'request_quotes',
        sa.column('decision', sa.String(length=16)),
    )
    bind.execute(
        request_quotes.update()
        .where(request_quotes.c.decision == 'Pending')
        .values(decision='Sent')
    )


def downgrade():
    bind = op.get_bind()
    request_quotes = sa.table(
        'request_quotes',
        sa.column('decision', sa.String(length=16)),
    )
    bind.execute(
        request_quotes.update()
        .where(request_quotes.c.decision == 'Sent')
        .values(decision='Pending')
    )
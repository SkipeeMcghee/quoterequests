"""add per-type request numbers

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2026-05-09 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'l5m6n7o8p9q0'
down_revision = 'k4l5m6n7o8p9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('quote_requests', sa.Column('request_number', sa.Integer(), nullable=True))

    bind = op.get_bind()
    quote_requests = sa.table(
        'quote_requests',
        sa.column('id', sa.Integer()),
        sa.column('request_type', sa.String(length=32)),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('request_number', sa.Integer()),
    )

    rows = bind.execute(
        sa.select(
            quote_requests.c.id,
            quote_requests.c.request_type,
        ).order_by(quote_requests.c.created_at.asc(), quote_requests.c.id.asc())
    ).all()

    request_type_counters: dict[str, int] = {}
    for row in rows:
        request_type = row.request_type or 'Quote request'
        request_type_counters[request_type] = request_type_counters.get(request_type, 0) + 1
        bind.execute(
            quote_requests.update()
            .where(quote_requests.c.id == row.id)
            .values(request_number=request_type_counters[request_type])
        )

    op.alter_column('quote_requests', 'request_number', nullable=False)
    op.create_unique_constraint(
        'uq_quote_requests_type_number',
        'quote_requests',
        ['request_type', 'request_number'],
    )


def downgrade():
    op.drop_constraint('uq_quote_requests_type_number', 'quote_requests', type_='unique')
    op.drop_column('quote_requests', 'request_number')
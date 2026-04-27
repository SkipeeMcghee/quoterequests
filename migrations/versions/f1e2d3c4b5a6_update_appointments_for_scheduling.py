"""update appointments for scheduling

Revision ID: f1e2d3c4b5a6
Revises: e7c8d9f0a1b2
Create Date: 2026-04-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1e2d3c4b5a6'
down_revision = 'e7c8d9f0a1b2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('appointments', sa.Column('customer_id', sa.Integer(), nullable=True))
    op.add_column('appointments', sa.Column('title', sa.String(length=255), nullable=True))
    op.add_column('appointments', sa.Column('scheduled_date', sa.Date(), nullable=True))
    op.add_column('appointments', sa.Column('start_time', sa.Time(), nullable=True))
    op.add_column('appointments', sa.Column('end_time', sa.Time(), nullable=True))
    op.create_index(op.f('ix_appointments_customer_id'), 'appointments', ['customer_id'], unique=False)
    op.create_foreign_key(
        'fk_appointments_customer_id_customers',
        'appointments',
        'customers',
        ['customer_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('fk_appointments_customer_id_customers', 'appointments', type_='foreignkey')
    op.drop_index(op.f('ix_appointments_customer_id'), table_name='appointments')
    op.drop_column('appointments', 'end_time')
    op.drop_column('appointments', 'start_time')
    op.drop_column('appointments', 'scheduled_date')
    op.drop_column('appointments', 'title')
    op.drop_column('appointments', 'customer_id')

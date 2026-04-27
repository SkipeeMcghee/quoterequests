"""add recurring work support

Revision ID: g1h2i3j4k5l6
Revises: f1e2d3c4b5a6
Create Date: 2026-04-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'g1h2i3j4k5l6'
down_revision = 'f1e2d3c4b5a6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'recurring_works',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('quote_request_id', sa.Integer(), nullable=True),
        sa.Column('source_appointment_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('frequency', sa.String(length=16), nullable=False),
        sa.Column('day_of_week', sa.SmallInteger(), nullable=True),
        sa.Column('day_of_month', sa.SmallInteger(), nullable=True),
        sa.Column('starts_on', sa.Date(), nullable=False),
        sa.Column('ends_on', sa.Date(), nullable=True),
        sa.Column('start_time', sa.Time(), nullable=True),
        sa.Column('end_time', sa.Time(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='active'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['quote_request_id'], ['quote_requests.id']),
        sa.ForeignKeyConstraint(['source_appointment_id'], ['appointments.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_recurring_works_customer_id'), 'recurring_works', ['customer_id'], unique=False)
    op.create_index(op.f('ix_recurring_works_quote_request_id'), 'recurring_works', ['quote_request_id'], unique=False)
    op.create_index(op.f('ix_recurring_works_source_appointment_id'), 'recurring_works', ['source_appointment_id'], unique=False)

    op.add_column('appointments', sa.Column('recurring_work_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_appointments_recurring_work_id'), 'appointments', ['recurring_work_id'], unique=False)
    op.create_foreign_key(
        'fk_appointments_recurring_work_id_recurring_works',
        'appointments',
        'recurring_works',
        ['recurring_work_id'],
        ['id'],
        ondelete='SET NULL',
    )

    op.alter_column('appointments', 'quote_request_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    op.alter_column('appointments', 'quote_request_id', existing_type=sa.Integer(), nullable=False)
    op.drop_constraint('fk_appointments_recurring_work_id_recurring_works', 'appointments', type_='foreignkey')
    op.drop_index(op.f('ix_appointments_recurring_work_id'), table_name='appointments')
    op.drop_column('appointments', 'recurring_work_id')

    op.drop_index(op.f('ix_recurring_works_source_appointment_id'), table_name='recurring_works')
    op.drop_index(op.f('ix_recurring_works_quote_request_id'), table_name='recurring_works')
    op.drop_index(op.f('ix_recurring_works_customer_id'), table_name='recurring_works')
    op.drop_table('recurring_works')

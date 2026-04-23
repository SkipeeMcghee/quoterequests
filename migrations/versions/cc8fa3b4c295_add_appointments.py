"""add appointments table

Revision ID: cc8fa3b4c295
Revises: b89c826e8a47
Create Date: 2026-04-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = 'cc8fa3b4c295'
down_revision = 'b89c826e8a47'
branch_labels = None
depend_on = None


def upgrade():
    op.create_table(
        'appointments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('quote_request_id', sa.Integer(), sa.ForeignKey('quote_requests.id'), nullable=False),
        sa.Column('requested_date', sa.Date(), nullable=True),
        sa.Column('requested_time_window', sa.String(length=120), nullable=True),
        sa.Column('confirmed_date', sa.Date(), nullable=True),
        sa.Column('confirmed_time_window', sa.String(length=120), nullable=True),
        sa.Column('customer_notes', sa.Text(), nullable=True),
        sa.Column('internal_notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default=sa.text("'Requested'")),
        sa.Column('previous_appointment_id', sa.Integer(), sa.ForeignKey('appointments.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f('ix_appointments_quote_request_id'), 'appointments', ['quote_request_id'], unique=False)
    op.create_index(op.f('ix_appointments_previous_appointment_id'), 'appointments', ['previous_appointment_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_appointments_previous_appointment_id'), table_name='appointments')
    op.drop_index(op.f('ix_appointments_quote_request_id'), table_name='appointments')
    op.drop_table('appointments')

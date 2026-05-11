"""add appointment service options

Revision ID: n7o8p9q0r1s2
Revises: m6n7o8p9q0r1
Create Date: 2026-05-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'n7o8p9q0r1s2'
down_revision = 'm6n7o8p9q0r1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'appointment_service_options',
        sa.Column('appointment_id', sa.Integer(), nullable=False),
        sa.Column('service_option_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['service_option_id'], ['service_options.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('appointment_id', 'service_option_id'),
    )


def downgrade():
    op.drop_table('appointment_service_options')
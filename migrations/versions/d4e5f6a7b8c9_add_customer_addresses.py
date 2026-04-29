"""add customer address records

Revision ID: d4e5f6a7b8c9
Revises: h1i2j3k4l5m6
Create Date: 2026-04-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = '9ece45639d31'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'customer_addresses',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('address_line_1', sa.String(length=255), nullable=True),
        sa.Column('address_line_2', sa.String(length=255), nullable=True),
        sa.Column('state', sa.String(length=255), nullable=True),
        sa.Column('zip_code', sa.String(length=20), nullable=True),
        sa.Column('is_billing', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )


def downgrade():
    op.drop_table('customer_addresses')

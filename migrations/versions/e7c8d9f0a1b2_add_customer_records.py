"""add customer records

Revision ID: e7c8d9f0a1b2
Revises: d0a1b2c3d4e5
Create Date: 2026-04-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7c8d9f0a1b2'
down_revision = 'd0a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'customers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('primary_name', sa.String(length=255), nullable=True),
        sa.Column('primary_email', sa.String(length=255), nullable=True),
        sa.Column('primary_phone', sa.String(length=50), nullable=True),
        sa.Column('primary_city', sa.String(length=255), nullable=True),
        sa.Column('billing_amount', sa.Numeric(10, 2), nullable=True),
        sa.Column('billing_frequency', sa.String(length=16), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("billing_frequency IN ('weekly','monthly','per_job')", name='ck_customers_billing_frequency'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_customers_primary_email'), 'customers', ['primary_email'], unique=False)
    op.create_index(op.f('ix_customers_primary_phone'), 'customers', ['primary_phone'], unique=False)

    op.create_table(
        'customer_fields',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('value', sa.String(length=255), nullable=False),
        sa.Column('is_primary', sa.Boolean(), nullable=False),
        sa.Column('source_quote_request_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_quote_request_id'], ['quote_requests.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('customer_id', 'kind', 'value', name='uq_customer_fields_customer_kind_value'),
    )
    op.create_index(op.f('ix_customer_fields_customer_id'), 'customer_fields', ['customer_id'], unique=False)

    op.create_table(
        'customer_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('note_text', sa.Text(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_customer_notes_customer_id'), 'customer_notes', ['customer_id'], unique=False)

    op.add_column('quote_requests', sa.Column('customer_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_quote_requests_customer_id'), 'quote_requests', ['customer_id'], unique=False)
    op.create_foreign_key(
        'fk_quote_requests_customer_id_customers',
        'quote_requests',
        'customers',
        ['customer_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint('fk_quote_requests_customer_id_customers', 'quote_requests', type_='foreignkey')
    op.drop_index(op.f('ix_quote_requests_customer_id'), table_name='quote_requests')
    op.drop_column('quote_requests', 'customer_id')

    op.drop_index(op.f('ix_customer_notes_customer_id'), table_name='customer_notes')
    op.drop_table('customer_notes')

    op.drop_index(op.f('ix_customer_fields_customer_id'), table_name='customer_fields')
    op.drop_table('customer_fields')

    op.drop_index(op.f('ix_customers_primary_phone'), table_name='customers')
    op.drop_index(op.f('ix_customers_primary_email'), table_name='customers')
    op.drop_table('customers')

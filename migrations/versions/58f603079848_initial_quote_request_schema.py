"""initial quote request schema

Revision ID: 58f603079848
Revises: 
Create Date: 2026-04-21 11:57:32.426241

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '58f603079848'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    op.create_table(
        'quote_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=50), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('service_type', sa.String(length=120), nullable=False),
        sa.Column('address', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('preferred_contact_method', sa.String(length=50), nullable=False),
        sa.Column('preferred_contact_time', sa.String(length=120), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_quote_requests_email'), 'quote_requests', ['email'], unique=False)

    op.create_table(
        'request_photos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quote_request_id', sa.Integer(), nullable=False),
        sa.Column('file_path', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['quote_request_id'], ['quote_requests.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_request_photos_quote_request_id'), 'request_photos', ['quote_request_id'], unique=False)

    op.create_table(
        'request_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quote_request_id', sa.Integer(), nullable=False),
        sa.Column('note_text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['quote_request_id'], ['quote_requests.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_request_notes_quote_request_id'), 'request_notes', ['quote_request_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_request_notes_quote_request_id'), table_name='request_notes')
    op.drop_table('request_notes')
    op.drop_index(op.f('ix_request_photos_quote_request_id'), table_name='request_photos')
    op.drop_table('request_photos')
    op.drop_index(op.f('ix_quote_requests_email'), table_name='quote_requests')
    op.drop_table('quote_requests')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')

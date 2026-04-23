"""add city and service options to quote_requests

Revision ID: b89c826e8a47
Revises: 58f603079848
Create Date: 2026-04-23 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b89c826e8a47'
down_revision = '58f603079848'
branch_labels = None
depends_on = None

DEFAULT_SERVICE_NAMES = [
    "Landscape Design",
    "Roof Repair",
    "Window Cleaning",
    "Inspection",
    "Painting",
    "Deck Staining",
    "Flooring",
    "Siding",
    "Fence Repair",
    "General Maintenance",
]


def upgrade():
    op.add_column('quote_requests', sa.Column('city', sa.String(length=255), nullable=True))
    op.alter_column('quote_requests', 'phone', existing_type=sa.String(length=50), nullable=True)
    op.alter_column('quote_requests', 'email', existing_type=sa.String(length=255), nullable=True)

    op.create_table(
        'service_options',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=120), nullable=False, unique=True),
    )

    op.create_table(
        'quote_request_service_options',
        sa.Column('quote_request_id', sa.Integer(), sa.ForeignKey('quote_requests.id'), primary_key=True, nullable=False),
        sa.Column('service_option_id', sa.Integer(), sa.ForeignKey('service_options.id'), primary_key=True, nullable=False),
    )

    conn = op.get_bind()
    service_options = sa.table('service_options', sa.column('id', sa.Integer), sa.column('name', sa.String))
    for name in DEFAULT_SERVICE_NAMES:
        conn.execute(sa.insert(service_options).values(name=name))

    quote_requests = sa.table(
        'quote_requests',
        sa.column('id', sa.Integer),
        sa.column('address', sa.String),
        sa.column('service_type', sa.String),
        sa.column('city', sa.String),
    )
    quote_request_service_options = sa.table(
        'quote_request_service_options',
        sa.column('quote_request_id', sa.Integer),
        sa.column('service_option_id', sa.Integer),
    )

    rows = conn.execute(sa.select(quote_requests.c.id, quote_requests.c.address, quote_requests.c.service_type)).fetchall()
    for row in rows:
        conn.execute(
            quote_requests.update()
            .where(quote_requests.c.id == row.id)
            .values(city=row.address)
        )

        if row.service_type is not None and row.service_type.strip():
            option_id = conn.execute(
                sa.select(service_options.c.id).where(service_options.c.name == row.service_type)
            ).scalar_one_or_none()
            if option_id is None:
                insert_result = conn.execute(sa.insert(service_options).values(name=row.service_type))
                option_id = insert_result.inserted_primary_key[0]
            conn.execute(
                sa.insert(quote_request_service_options).values(
                    quote_request_id=row.id,
                    service_option_id=option_id,
                )
            )

    op.alter_column('quote_requests', 'city', existing_type=sa.String(length=255), nullable=False)

    op.drop_column('quote_requests', 'service_type')
    op.drop_column('quote_requests', 'address')
    op.drop_column('quote_requests', 'description')
    op.drop_column('quote_requests', 'preferred_contact_method')
    op.drop_column('quote_requests', 'preferred_contact_time')


def downgrade():
    op.add_column('quote_requests', sa.Column('service_type', sa.String(length=120), nullable=True))
    op.add_column('quote_requests', sa.Column('address', sa.String(length=255), nullable=True))
    op.add_column('quote_requests', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('quote_requests', sa.Column('preferred_contact_method', sa.String(length=50), nullable=True))
    op.add_column('quote_requests', sa.Column('preferred_contact_time', sa.String(length=120), nullable=True))

    quote_requests = sa.table(
        'quote_requests',
        sa.column('id', sa.Integer),
        sa.column('city', sa.String),
    )
    service_options = sa.table('service_options', sa.column('id', sa.Integer), sa.column('name', sa.String))
    quote_request_service_options = sa.table(
        'quote_request_service_options',
        sa.column('quote_request_id', sa.Integer),
        sa.column('service_option_id', sa.Integer),
    )

    conn = op.get_bind()
    rows = conn.execute(sa.select(quote_requests.c.id, quote_requests.c.city)).fetchall()
    for row in rows:
        conn.execute(
            quote_requests.update()
            .where(quote_requests.c.id == row.id)
            .values(address=row.city)
        )

    association_rows = conn.execute(sa.select(quote_request_service_options.c.quote_request_id, quote_request_service_options.c.service_option_id)).fetchall()
    for row in association_rows:
        option_name = conn.execute(
            sa.select(service_options.c.name).where(service_options.c.id == row.service_option_id)
        ).scalar_one_or_none()
        if option_name is not None:
            conn.execute(
                quote_requests.update()
                .where(quote_requests.c.id == row.quote_request_id)
                .values(service_type=option_name)
            )

    op.drop_table('quote_request_service_options')
    op.drop_table('service_options')

    op.alter_column('quote_requests', 'email', existing_type=sa.String(length=255), nullable=False)
    op.alter_column('quote_requests', 'phone', existing_type=sa.String(length=50), nullable=False)

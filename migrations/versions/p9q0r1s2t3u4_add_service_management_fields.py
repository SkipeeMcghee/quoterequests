"""add service management fields

Revision ID: p9q0r1s2t3u4
Revises: o8p9q0r1s2t3
Create Date: 2026-05-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "p9q0r1s2t3u4"
down_revision = "o8p9q0r1s2t3"
branch_labels = None
depends_on = None


DEFAULT_SERVICES = (
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
)


def upgrade() -> None:
    op.add_column("service_options", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "service_options",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "service_options",
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(op.f("ix_service_options_is_active"), "service_options", ["is_active"], unique=False)
    op.create_index(op.f("ix_service_options_display_order"), "service_options", ["display_order"], unique=False)

    service_options = sa.table(
        "service_options",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String(length=120)),
        sa.column("description", sa.Text()),
        sa.column("is_active", sa.Boolean()),
        sa.column("display_order", sa.Integer()),
    )
    connection = op.get_bind()
    existing_rows = connection.execute(
        sa.select(service_options.c.id, service_options.c.name)
        .order_by(service_options.c.name.asc(), service_options.c.id.asc())
    ).mappings().all()

    if existing_rows:
        for index, row in enumerate(existing_rows):
            connection.execute(
                service_options.update()
                .where(service_options.c.id == row["id"])
                .values(display_order=index, is_active=True)
            )
    else:
        connection.execute(
            service_options.insert(),
            [
                {
                    "name": name,
                    "description": None,
                    "is_active": True,
                    "display_order": index,
                }
                for index, name in enumerate(DEFAULT_SERVICES)
            ],
        )

    op.alter_column("service_options", "is_active", server_default=None)
    op.alter_column("service_options", "display_order", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_service_options_display_order"), table_name="service_options")
    op.drop_index(op.f("ix_service_options_is_active"), table_name="service_options")
    op.drop_column("service_options", "display_order")
    op.drop_column("service_options", "is_active")
    op.drop_column("service_options", "description")
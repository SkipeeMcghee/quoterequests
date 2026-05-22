"""add gallery items

Revision ID: q0r1s2t3u4v5
Revises: p9q0r1s2t3u4
Create Date: 2026-05-22 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "q0r1s2t3u4v5"
down_revision = "p9q0r1s2t3u4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gallery_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("caption", sa.String(length=180), nullable=True),
        sa.Column("service_id", sa.Integer(), nullable=True),
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["service_id"], ["service_options.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_gallery_items_service_id"), "gallery_items", ["service_id"], unique=False)
    op.create_index(op.f("ix_gallery_items_featured"), "gallery_items", ["featured"], unique=False)
    op.create_index(op.f("ix_gallery_items_is_active"), "gallery_items", ["is_active"], unique=False)
    op.create_index(op.f("ix_gallery_items_display_order"), "gallery_items", ["display_order"], unique=False)
    op.alter_column("gallery_items", "featured", server_default=None)
    op.alter_column("gallery_items", "is_active", server_default=None)
    op.alter_column("gallery_items", "display_order", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_gallery_items_display_order"), table_name="gallery_items")
    op.drop_index(op.f("ix_gallery_items_is_active"), table_name="gallery_items")
    op.drop_index(op.f("ix_gallery_items_featured"), table_name="gallery_items")
    op.drop_index(op.f("ix_gallery_items_service_id"), table_name="gallery_items")
    op.drop_table("gallery_items")
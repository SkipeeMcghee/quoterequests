"""add request quote tracking

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-05-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "j3k4l5m6n7o8"
down_revision = "i2j3k4l5m6n7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("quote_requests", sa.Column("first_viewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "request_quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("quote_request_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["quote_request_id"], ["quote_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_request_quotes_quote_request_id"), "request_quotes", ["quote_request_id"], unique=False)

    quote_requests = sa.table(
        "quote_requests",
        sa.column("id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("last_contacted_on", sa.Date),
        sa.column("first_viewed_at", sa.DateTime(timezone=True)),
    )

    connection = op.get_bind()
    connection.execute(
        quote_requests.update().where(quote_requests.c.status == "Won").values(status="Accepted")
    )
    connection.execute(
        quote_requests.update().where(quote_requests.c.status == "Lost").values(status="Rejected")
    )
    connection.execute(
        quote_requests.update()
        .where(
            sa.or_(
                quote_requests.c.status != "New",
                quote_requests.c.last_contacted_on.is_not(None),
            )
        )
        .values(first_viewed_at=quote_requests.c.created_at)
    )


def downgrade() -> None:
    quote_requests = sa.table(
        "quote_requests",
        sa.column("status", sa.String),
    )

    connection = op.get_bind()
    connection.execute(
        quote_requests.update().where(quote_requests.c.status == "Accepted").values(status="Won")
    )
    connection.execute(
        quote_requests.update().where(quote_requests.c.status == "Rejected").values(status="Lost")
    )

    op.drop_index(op.f("ix_request_quotes_quote_request_id"), table_name="request_quotes")
    op.drop_table("request_quotes")
    op.drop_column("quote_requests", "first_viewed_at")
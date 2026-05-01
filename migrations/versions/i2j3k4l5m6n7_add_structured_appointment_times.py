"""add structured appointment requested and confirmed times

Revision ID: i2j3k4l5m6n7
Revises: 50c4646b8440
Create Date: 2026-05-01 00:00:00.000000
"""

from __future__ import annotations

import re
from datetime import time

from alembic import op
import sqlalchemy as sa


revision = 'i2j3k4l5m6n7'
down_revision = '50c4646b8440'
branch_labels = None
depends_on = None


LEGACY_TIME_PATTERN = re.compile(
    r"(?P<hour>1[0-2]|0?[1-9])(?::(?P<minute>[0-5]\d))?\s*(?P<period>am|pm)",
    re.IGNORECASE,
)


def _parse_legacy_time(value: str | None) -> time | None:
    if not value:
        return None

    match = LEGACY_TIME_PATTERN.search(value)
    if match is None:
        return None

    hour_value = int(match.group("hour"))
    minute_value = int(match.group("minute") or 0)
    period = match.group("period").lower()

    if period == "pm" and hour_value != 12:
        hour_value += 12
    if period == "am" and hour_value == 12:
        hour_value = 0

    return time(hour=hour_value, minute=minute_value)


def upgrade():
    op.add_column('appointments', sa.Column('requested_time', sa.Time(), nullable=True))
    op.add_column('appointments', sa.Column('confirmed_time', sa.Time(), nullable=True))

    bind = op.get_bind()
    appointments = sa.table(
        'appointments',
        sa.column('id', sa.Integer()),
        sa.column('requested_time_window', sa.String(length=120)),
        sa.column('confirmed_time_window', sa.String(length=120)),
        sa.column('requested_time', sa.Time()),
        sa.column('confirmed_time', sa.Time()),
    )

    rows = bind.execute(
        sa.select(
            appointments.c.id,
            appointments.c.requested_time_window,
            appointments.c.confirmed_time_window,
        )
    ).fetchall()

    for row in rows:
        requested_time = _parse_legacy_time(row.requested_time_window)
        confirmed_time = _parse_legacy_time(row.confirmed_time_window)
        if requested_time is None and confirmed_time is None:
            continue

        bind.execute(
            appointments.update()
            .where(appointments.c.id == row.id)
            .values(requested_time=requested_time, confirmed_time=confirmed_time)
        )


def downgrade():
    op.drop_column('appointments', 'confirmed_time')
    op.drop_column('appointments', 'requested_time')
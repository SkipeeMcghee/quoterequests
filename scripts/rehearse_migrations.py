"""Rehearse `flask db upgrade` against a clean PostgreSQL schema.

Deploy day is the wrong time to discover a migration that only ever ran on SQLite.

This script builds the entire schema from scratch inside a throwaway schema in the
configured PostgreSQL database (it does not touch the existing data), then compares the
result to the SQLAlchemy models so drift shows up before a customer sees it.

Usage:
    python scripts/rehearse_migrations.py                # rehearse, report, clean up
    python scripts/rehearse_migrations.py --keep         # leave the schema for inspection
    python scripts/rehearse_migrations.py --schema mytest

Exit code 0 when migrations build cleanly and match the models.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def postgres_dsn() -> str:
    from app.config import DevelopmentConfig

    url = os.environ.get("DATABASE_URL") or DevelopmentConfig.SQLALCHEMY_DATABASE_URI
    url = url.replace("postgresql+psycopg", "postgresql").replace("postgresql+psycopg2", "postgresql")
    if not url.startswith("postgresql"):
        raise SystemExit(
            "DATABASE_URL does not point at PostgreSQL; this rehearsal only means "
            "something against the engine production will use."
        )
    return url


def mask(value: str) -> str:
    return re.sub(r"(://[^:]+:)[^@]+@", r"\1***@", value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", default="migration_rehearsal")
    parser.add_argument("--keep", action="store_true", help="keep the rehearsal schema")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="also write a customer, request and appointment through the ORM",
    )
    args = parser.parse_args(argv)

    import psycopg
    from sqlalchemy import event, inspect

    dsn = postgres_dsn()
    print(f"database: {mask(dsn)}")
    print(f"schema:   {args.schema}")

    with psycopg.connect(dsn, connect_timeout=10) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{args.schema}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{args.schema}"')

    # Point every app connection at the rehearsal schema before the app touches it.
    import app.config as config_module

    config_module.DevelopmentConfig.SQLALCHEMY_DATABASE_URI = dsn.replace(
        "postgresql://", "postgresql+psycopg://"
    )

    from app import create_app
    from app.extensions import db

    app = create_app("development")
    app.config.update(SQLALCHEMY_DATABASE_URI=config_module.DevelopmentConfig.SQLALCHEMY_DATABASE_URI)

    schema = args.schema

    import logging

    logging.getLogger("alembic").setLevel(logging.WARNING)

    from alembic.script import ScriptDirectory
    from flask_migrate import upgrade

    script_dir = ScriptDirectory(str(REPO_ROOT / "migrations"))
    expected_head = script_dir.get_current_head()

    with app.app_context():
        # Point every pooled connection at the rehearsal schema before anything queries.
        @event.listens_for(db.engine, "connect")
        def _set_search_path(dbapi_connection, _record):  # noqa: ANN001
            previous_autocommit = dbapi_connection.autocommit
            dbapi_connection.autocommit = True
            with dbapi_connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{schema}"')
            dbapi_connection.autocommit = previous_autocommit

        print("running upgrade ...")
        upgrade(directory=str(REPO_ROOT / "migrations"))
        current = db.session.execute(db.text("select version_num from alembic_version")).scalar()

        print(f"alembic head: {expected_head} -> applied: {current}")
        if current != expected_head:
            print("FAIL: database is not at the script head")
            return 1

        problems: list[str] = []
        inspector = inspect(db.engine)
        live_tables = set(inspector.get_table_names(schema=schema))
        model_tables = set(db.metadata.tables)

        missing = model_tables - live_tables
        extra = live_tables - model_tables - {"alembic_version"}
        if missing:
            problems.append(f"tables in models but not in the database: {sorted(missing)}")
        if extra:
            problems.append(f"tables in the database but not in models: {sorted(extra)}")

        for name in sorted(model_tables & live_tables):
            live_columns = {column["name"] for column in inspector.get_columns(name, schema=schema)}
            model_columns = set(db.metadata.tables[name].columns.keys())
            if live_columns != model_columns:
                problems.append(
                    f"{name}: columns differ (missing {sorted(model_columns - live_columns)}, "
                    f"extra {sorted(live_columns - model_columns)})"
                )

        if args.smoke:
            problems.extend(_smoke_write(db))

    print(f"tables created: {len(live_tables)}")

    if problems:
        print("\nDRIFT:")
        for problem in problems:
            print("  -", problem)
    else:
        print("no drift: migrations produce exactly the model schema")

    if not args.keep:
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        print("rehearsal schema dropped")
    else:
        print(f"rehearsal schema kept: {schema}")

    return 1 if problems else 0


def _smoke_write(db) -> list[str]:
    """Insert and read back one of each core record, using the real models."""

    from datetime import date, time

    from app.models import Appointment, Customer, QuoteRequest, User

    problems: list[str] = []
    try:
        user = User(email="rehearsal@example.test")
        user.set_password("rehearsal-password")
        customer = Customer(primary_name="Rehearsal Customer", primary_city="Daytona Beach")
        db.session.add_all([user, customer])
        db.session.flush()

        quote_request = QuoteRequest(
            request_number=0,
            full_name="Rehearsal Customer",
            city="Daytona Beach",
            email="rehearsal@example.test",
            customer=customer,
        )
        db.session.add(quote_request)
        db.session.flush()

        appointment = Appointment(
            customer=customer,
            quote_request=quote_request,
            title="Rehearsal appointment",
            scheduled_date=date.today(),
            start_time=time(9, 0),
            end_time=time(10, 0),
            status="Scheduled",
        )
        db.session.add(appointment)
        db.session.commit()

        if Appointment.query.count() != 1 or QuoteRequest.query.count() != 1:
            problems.append("smoke write: rows did not persist")
        else:
            print("smoke write: customer + request + appointment committed and read back")
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        problems.append(f"smoke write failed: {type(exc).__name__}: {exc}")

    return problems


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import click
import json
from pathlib import Path
from contextlib import contextmanager

from flask import Flask
from flask_migrate import upgrade
from sqlalchemy.engine import URL

from app.extensions import db
from app.models import User
from app.tenancy import (
    TenantRegistry, database_identity, get_registry, read_tenant_records,
    tenant_operation, tenant_registry_write_lock, tenant_upload_root, write_tenant_records,
)

MIGRATIONS = str(Path(__file__).resolve().parents[1] / "migrations")


def register_cli(app: Flask) -> None:
    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.password_option("--password", prompt=True, confirmation_prompt=True)
    @click.option("--tenant", "tenant_slug")
    def create_admin(email: str, password: str, tenant_slug: str | None) -> None:
        with _cli_tenant(tenant_slug):
            normalized_email = _create_admin_user(email, password)
        click.echo(f"Admin user created for {normalized_email}.")

    @app.cli.command("create-dev-admin")
    @click.option("--email", default="admin@local.test", show_default=True)
    @click.option("--password", default="TempPass123!", show_default=True)
    @click.option("--tenant", "tenant_slug")
    def create_dev_admin(email: str, password: str, tenant_slug: str | None) -> None:
        with _cli_tenant(tenant_slug):
            normalized_email = _create_admin_user(email, password)
        click.echo("Development admin user created.")
        click.echo(f"Email: {normalized_email}")
        click.echo(f"Password: {password}")

    @app.cli.group("tenant")
    def tenant_commands() -> None:
        """Provision and inspect isolated tenants."""

    @tenant_commands.command("list")
    def list_tenants() -> None:
        for tenant in get_registry().tenants.values():
            click.echo(f"{tenant.slug}\t{','.join(tenant.hosts)}\t{'enabled' if tenant.enabled else 'disabled'}")

    @tenant_commands.command("upgrade")
    @click.argument("slug")
    @click.option("--revision", default="head", show_default=True)
    def upgrade_tenant(slug: str, revision: str) -> None:
        with _cli_tenant(slug):
            upgrade(directory=MIGRATIONS, revision=revision)
        click.echo(f"Tenant {slug} migrated to {revision}.")

    @tenant_commands.command("create")
    @click.argument("slug")
    @click.option("--domain", multiple=True, required=True)
    @click.option("--database-uri", help="Existing PostgreSQL database URI; defaults to a dedicated SQLite file.")
    @click.option("--settings", default="{}", help="JSON object of tenant settings.")
    @click.option("--admin-email")
    @click.option("--admin-password", help="Omit to enter a hidden password prompt.")
    def create_tenant(slug: str, domain: tuple[str, ...], database_uri: str | None,
                      settings: str, admin_email: str | None, admin_password: str | None) -> None:
        if admin_password and not admin_email:
            raise click.ClickException("--admin-password requires --admin-email.")
        if admin_email and admin_password is None:
            admin_password = click.prompt("Admin password", hide_input=True, confirmation_prompt=True)
        try:
            overrides = json.loads(settings)
            with tenant_registry_write_lock() as path:
                records = read_tenant_records(path)
                old = get_registry()
                latest = TenantRegistry.from_config(app.config)
                if slug in latest.tenants:
                    raise ValueError("Tenant slug already exists.")
                if database_uri is None:
                    database_uri = URL.create("sqlite+pysqlite", database=str(
                        Path(app.instance_path).resolve() / "tenants" / slug / "tenant.sqlite3",
                    )).render_as_string(hide_password=False)
                record = {"hosts": list(domain), "database_uri": database_uri, "settings": overrides}
                # Validate the complete registry before creating directories or contacting a DB.
                config = dict(app.config)
                config["TENANT_REGISTRY_FILE"] = ""
                configured = {
                    name: {"hosts": list(item.hosts), "database_uri": item.database_uri,
                           "enabled": item.enabled, "settings": _plain_settings(item.settings)}
                    for name, item in latest.tenants.items()
                }
                config["TENANTS"] = {**configured, slug: record}
                candidate = TenantRegistry.from_config(config)
                candidate.bind_engines(app, db.engine)
                try:
                    engine = candidate.engine_for(candidate.tenants[slug])
                    if engine.url.get_backend_name() not in ("sqlite", "postgresql"):
                        raise ValueError("Provisioning supports PostgreSQL and SQLite only.")
                    if engine.url.get_backend_name() == "sqlite" and (
                        engine.url.database in (None, "", ":memory:") or engine.url.query.get("uri")
                    ):
                        raise ValueError("Provisioning requires a persistent, ordinary SQLite file URI.")
                    identity = database_identity(engine)
                    if identity in {database_identity(item.database_uri) for item in latest.tenants.values()} or identity == database_identity(db.engine):
                        raise ValueError("The new tenant must use a dedicated database.")
                    app.extensions["tenancy"] = candidate
                    with tenant_operation(slug):
                        upload_root = tenant_upload_root()
                        if engine.url.get_backend_name() == "sqlite":
                            Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
                        upgrade(directory=MIGRATIONS)
                        for category in ("quote_requests", "customers", "gallery"):
                            (upload_root / category).mkdir(parents=True, exist_ok=True)
                        if admin_email:
                            assert admin_password is not None
                            _create_admin_user(admin_email, admin_password)
                    write_tenant_records(path, {**records, slug: record})
                except Exception:
                    app.extensions["tenancy"] = old
                    for item in candidate.engines.values():
                        item.dispose()
                    raise
                for item in old.engines.values():
                    if item is not db.engine:
                        item.dispose()
        except (ValueError, OSError) as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"Tenant {slug} provisioned. Restart application workers to load the registry.")


def _plain_settings(value):
    from collections.abc import Mapping
    return {key: _plain_settings(item) for key, item in value.items()} if isinstance(value, Mapping) else value


@contextmanager
def _cli_tenant(slug: str | None):
    try:
        with tenant_operation(slug) as tenant:
            yield tenant
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def _create_admin_user(email: str, password: str) -> str:
    normalized_email = email.strip().lower()
    if not normalized_email or not password:
        raise click.ClickException("An email and a nonempty password are required.")
    existing_user = User.query.filter_by(email=normalized_email).first()
    if existing_user is not None:
        raise click.ClickException("A user with that email already exists.")

    user = User(email=normalized_email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return normalized_email
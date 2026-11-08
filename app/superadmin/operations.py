"""Platform operations without borrowing a platform request's tenant/session.

Requires tenancy.get_registry() to honour g._operator_registry and tenancy's
refresh_registry(app, force=True). Authorization and audit belong to the caller.
"""

from __future__ import annotations

import json
import re
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from functools import wraps
from pathlib import Path
from types import MappingProxyType
from typing import Any

from alembic.script import ScriptDirectory
from flask import current_app, g
from flask_migrate import upgrade
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

from app.cli import MIGRATIONS, _create_admin_user
from app.extensions import db
from app.services import themes
from app.services.demo import seed_demo
from app.services.public_pages import DEFAULT_PRESET, preset_names, validate_public_settings
from app.tenancy import (
    Tenant,
    TenantRegistry,
    current_tenant_settings,
    database_identity,
    get_registry,
    normalize_host,
    read_tenant_records,
    tenant_registry_write_lock,
    tenant_upload_root,
    write_tenant_records,
)
from scripts import backup


FEATURE_FLAGS = (
    "ENABLE_SERVICES", "ENABLE_GALLERY", "ENABLE_SCHEDULING",
    "ENABLE_STAFF_MANAGEMENT", "ENABLE_CUSTOMER_RECORDS", "ENABLE_CALENDAR",
    "ENABLE_RECURRING_WORK",
)
IDENTITY_FIELDS = (
    "BUSINESS_NAME", "BUSINESS_PHONE", "BUSINESS_EMAIL", "TAGLINE",
    "SERVICE_AREA", "BUSINESS_ADDRESS",
)
_COUNTED_TABLES = (
    "users", "quote_requests", "customers", "service_options", "gallery_items",
)
_MISSING = object()


class _ValidationError(ValueError):
    """Only deliberately credential-free validation messages reach the UI."""


def _safe_action(message):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except _ValidationError:
                raise
            except (Exception, SystemExit):
                # In particular, pg_dump and SQLAlchemy errors may contain secrets.
                raise ValueError(message) from None
        return wrapped
    return decorate


def _value(form, name: str, default: Any = _MISSING) -> Any:
    """Accept WTForms fields or a mapping, with lowercase UI field names."""
    for key in dict.fromkeys((name, name.lower(), name.upper())):
        value = form.get(key, _MISSING) if isinstance(form, Mapping) else getattr(form, key, _MISSING)
        if value is not _MISSING:
            return getattr(value, "data", value)
    return default


def _string(value: Any) -> str:
    if not isinstance(value, str):
        raise _ValidationError("Expected a text field.")
    return value.strip()


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, "", "0", "false", "off", "no", 0):
        return False
    if value in ("1", "true", "on", "yes", "y", 1):
        return True
    raise _ValidationError("Invalid checkbox value.")


def _slug(value: Any) -> str:
    slug = _string(value)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug):
        raise _ValidationError("Tenant slug must use lowercase letters, digits, underscores or hyphens.")
    return slug


def _hosts(form) -> list[str]:
    raw = _value(form, "domains", _MISSING)
    if raw is _MISSING:
        raw = _value(form, "hosts", "")
    parts = re.split(r"[,\s]+", _string(raw)) if isinstance(raw, str) else raw
    if not isinstance(parts, (list, tuple)):
        raise _ValidationError("Supply one or more tenant domains.")
    try:
        hosts = list(dict.fromkeys(normalize_host(part) for part in parts if part))
        reserved = current_app.config.get("SUPERADMIN_HOST", "")
        if reserved and normalize_host(reserved) in hosts:
            raise _ValidationError("The platform control host is reserved.")
        # normalize_host strips IPv6 brackets; retain them for registry revalidation
        # and for the effective HTTPS origin constructed from the primary host.
        hosts = [f"[{host}]" if ":" in host else host for host in hosts]
    except _ValidationError:
        raise
    except (ValueError, UnicodeError, TypeError, AttributeError):
        raise _ValidationError("Invalid tenant domain.") from None
    if not hosts:
        raise _ValidationError("Supply one or more tenant domains.")
    return hosts


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _record(tenant: Tenant) -> dict[str, Any]:
    return {"hosts": list(tenant.hosts), "database_uri": tenant.database_uri,
            "enabled": tenant.enabled, "settings": _plain(tenant.settings)}


def _candidate(latest: TenantRegistry, slug: str, record: Mapping[str, Any]) -> TenantRegistry:
    config = dict(current_app.config)
    config.update(TENANT_REGISTRY_FILE="", TENANTS_JSON="", TENANT_ALLOW_DEFAULT=False,
                  TENANTS={**{name: _record(item) for name, item in latest.tenants.items()}, slug: record})
    try:
        candidate = TenantRegistry.from_config(config)
    except Exception:
        raise _ValidationError("Invalid tenant configuration or domain already assigned.") from None
    # A materialized fallback tenant still uses the application's default engine.
    candidate.default_slug = latest.default_slug
    return candidate


def _settings(form, existing: Mapping[str, Any] | None = None) -> dict[str, Any]:
    settings = _plain(existing or {})
    for key in IDENTITY_FIELDS:
        value = _value(form, key)
        if value is not _MISSING:
            settings[key] = _string(value)
    for key in FEATURE_FLAGS:
        value = _value(form, key)
        if value is not _MISSING:
            settings[key] = _boolean(value)
    preset = _value(form, "SITE_PRESET")
    if preset is not _MISSING:
        preset = _string(preset)
        if preset not in preset_names():
            raise _ValidationError("Choose a known public site preset.")
        settings["SITE_PRESET"] = preset
    manifest = _value(form, "PUBLIC_PAGES_CONFIG")
    if manifest is not _MISSING:
        try:
            if isinstance(manifest, str):
                manifest = json.loads(manifest, object_pairs_hook=_unique_public_object,
                                      parse_constant=_invalid_public_constant) if manifest.strip() else {}
            elif isinstance(manifest, (Mapping, list)):
                manifest = _plain(manifest)
            else:
                raise ValueError()
        except ValueError:
            raise _ValidationError("Public pages manifest must be valid JSON without duplicate keys or nonfinite numbers.") from None
        settings["PUBLIC_PAGES_CONFIG"] = manifest
    candidate = {**current_app.config, **settings}
    try:
        validate_public_settings(
            candidate.get("SITE_PRESET", DEFAULT_PRESET),
            _plain(candidate.get("PUBLIC_PAGES_CONFIG", {})),
        )
    except ValueError:
        raise _ValidationError("Invalid public site preset or pages manifest; check the documented schema and safe URLs.") from None
    return settings


def _unique_public_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate manifest key.")
        result[key] = value
    return result


def _invalid_public_constant(value):
    raise ValueError("Nonfinite manifest number.")


def _storage_path(path: Path) -> Path:
    path = path.absolute()
    # Check every component, including ancestors of a not-yet-created directory.
    if any(item.is_symlink() for item in (path, *path.parents)) or path.resolve() != path:
        raise _ValidationError("Storage paths must not redirect through symlinks.")
    return path


def _sqlite_path(database) -> Path | None:
    url = database.url if hasattr(database, "url") else make_url(database)
    if url.get_backend_name() != "sqlite":
        return None
    if url.database in (None, "", ":memory:") or url.query.get("mode") == "memory":
        raise _ValidationError("A persistent SQLite database is required.")
    # URI-mode SQLite can alias memory databases or obscure the storage identity.
    if url.query.get("uri") or url.database.startswith("file:"):
        raise _ValidationError("Use an ordinary, persistent SQLite file URI.")
    path = Path(url.database)
    if not path.is_absolute():
        path = Path(current_app.instance_path) / path
    return _storage_path(path)


@contextmanager
def operator_context(tenant: Tenant, registry: TenantRegistry | None = None) -> Generator[Tenant, None, None]:
    """Locally enable one target; never mutate or dispose a shared registry."""
    app = current_app._get_current_object()
    source = registry if registry is not None else get_registry()
    target = replace(tenant, enabled=True)
    local = TenantRegistry(
        [target if item.slug == target.slug else item for item in source.tenants.values()]
        + ([] if target.slug in source.tenants else [target]),
        default_slug=source.default_slug,
    )
    shared = app.extensions.get("tenancy")
    engines = {}
    for item in local.tenants.values():
        if not item.enabled:
            continue
        for provider in (source, shared):
            if provider is None:
                continue
            original = provider.tenants.get(item.slug)
            engine = provider.engines.get(item.slug)
            if original is not None and original.enabled and engine is not None and original.database_uri == item.database_uri:
                engines[item.slug] = engine
                break
    temporary = None
    with app.app_context():
        g._operator_registry = local
        g.tenant = local.tenants[target.slug]
        try:
            if target.slug not in engines:
                temporary = TenantRegistry([g.tenant], default_slug=local.default_slug)
                temporary.bind_engines(app, db.engine)
                engines[target.slug] = temporary.engine_for(g.tenant)
            local.engines = MappingProxyType(engines)
            yield g.tenant
        finally:
            try:
                db.session.remove()
            finally:
                if temporary is not None:
                    for engine in temporary.engines.values():
                        if engine is not db.engine:
                            engine.dispose()
                g.pop("tenant", None)
                g.pop("_operator_registry", None)


def _refresh(app) -> None:
    # Imported lazily: the tenancy refresh API is supplied by the integration.
    from app.tenancy import refresh_registry
    refresh_registry(app, force=True)


@_safe_action("Tenant provisioning failed; check database, storage and registry configuration.")
def provision_tenant(form) -> Tenant:
    app = current_app._get_current_object()
    slug = _slug(_value(form, "slug", ""))
    hosts = _hosts(form)
    settings = _settings(form)
    demo = _boolean(_value(form, "demo_tenant", _value(form, "demo", False)))
    seed = _boolean(_value(form, "seed_demo", False))
    if seed and not demo:
        raise _ValidationError("Demo seeding requires a demo tenant.")
    if demo:
        settings.update(DEMO_TENANT=True, EMAIL_ENABLED=False)
    email = _string(_value(form, "admin_email", ""))
    password = _value(form, "admin_password", "")
    if bool(email) != bool(password) or not isinstance(password, str):
        raise _ValidationError("Supply both initial admin email and password, or neither.")
    with tenant_registry_write_lock() as path:
        records = read_tenant_records(path)
        latest = TenantRegistry.from_config(app.config)
        if slug in latest.tenants:
            raise _ValidationError("Tenant slug already exists.")
        storage = _storage_path(Path(app.instance_path) / "tenants" / slug)
        uri = _value(form, "database_uri", "")
        uri = _string(uri) if uri is not None else ""
        if not uri:
            uri = URL.create("sqlite+pysqlite", database=str(storage / "tenant.sqlite3")).render_as_string(hide_password=False)
        url = make_url(uri)
        if url.get_backend_name() not in ("sqlite", "postgresql"):
            raise _ValidationError("Provisioning supports SQLite and PostgreSQL only.")
        sqlite_path = _sqlite_path(uri)
        identity = database_identity(uri)
        identities = {database_identity(item.database_uri) for item in latest.tenants.values()}
        if identity in identities or identity == database_identity(db.engine):
            raise _ValidationError("The tenant must use a dedicated database.")
        # Do not silently take over an existing SQLite database at an unused URI.
        if sqlite_path is not None and sqlite_path.exists():
            raise _ValidationError("The new tenant SQLite database must not already exist.")
        record = {"hosts": hosts, "database_uri": uri, "enabled": True, "settings": settings}
        candidate = _candidate(latest, slug, record)
        # Reject redirected existing upload directories before any DB side effects.
        uploads = _storage_path(storage / "uploads")
        for category in ("quote_requests", "customers", "gallery"):
            _storage_path(uploads / category)
        with operator_context(candidate.tenants[slug], registry=candidate):
            if sqlite_path is not None:
                sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            upgrade(directory=MIGRATIONS)
            uploads = _storage_path(tenant_upload_root())
            for category in ("quote_requests", "customers", "gallery"):
                (uploads / category).mkdir(parents=True, exist_ok=True)
            if email:
                _create_admin_user(email, password)
            if seed:
                seed_demo()
        write_tenant_records(path, {**records, slug: record})
        _refresh(app)
        return candidate.tenants[slug]


@_safe_action("Tenant update failed; check registry configuration.")
def update_tenant(slug: str, form, toggle: bool = False) -> Tenant:
    app = current_app._get_current_object()
    slug = _slug(slug)
    with tenant_registry_write_lock() as path:
        records = read_tenant_records(path)
        latest = TenantRegistry.from_config(app.config)
        if slug not in latest.tenants:
            raise _ValidationError("Unknown tenant.")
        if slug not in records:
            raise _ValidationError("Static tenants cannot be edited here; edit deployment configuration.")
        tenant = latest.tenants[slug]
        record = _plain(records[slug])
        if toggle:
            record["enabled"] = not tenant.enabled
        else:
            settings = _settings(form, tenant.settings)
            raw_domains = _value(form, "domains", _value(form, "hosts"))
            if raw_domains is not _MISSING:
                hosts = _hosts(form)
                if tuple(normalize_host(host) for host in hosts) != tuple(normalize_host(host) for host in tenant.hosts):
                    # Explicit empty override also suppresses a deployment-wide origin.
                    settings["CANONICAL_ORIGIN"] = ""
                record["hosts"] = hosts
            record["settings"] = settings
        candidate = _candidate(latest, slug, record)
        write_tenant_records(path, {**records, slug: record})
        _refresh(app)
        return candidate.tenants[slug]


@_safe_action("Tenant migration failed.")
def migrate_tenant(tenant: Tenant) -> None:
    with operator_context(tenant):
        _sqlite_path(get_registry().engine_for(g.tenant))
        upgrade(directory=MIGRATIONS)


@_safe_action("Tenant backup failed.")
def backup_tenant(tenant: Tenant) -> str:
    app = current_app._get_current_object()
    with operator_context(tenant) as target:
        engine = get_registry().engine_for(target)
        sqlite_path = _sqlite_path(engine)
        if sqlite_path is not None and not sqlite_path.is_file():
            raise _ValidationError("Tenant database file is missing.")
        root = _storage_path(Path(app.instance_path) / "platform-backups" / _slug(target.slug))
        uploads = _storage_path(tenant_upload_root())
        theme = _storage_path(Path(app.instance_path) / "theme.json" if target.slug == get_registry().default_slug else uploads.parent / "theme.json")
        artifact = backup.backup_tenant(root, keep=7, tenant=target, engine=engine, uploads_dir=uploads, theme=theme)
        return str(artifact)


@_safe_action("Demo reset failed.")
def reset_demo(tenant: Tenant, confirmation: str) -> bool:
    if confirmation != tenant.slug:
        raise _ValidationError("Enter the exact tenant slug to confirm reset.")
    with operator_context(tenant):
        if current_tenant_settings().get("DEMO_TENANT") is not True:
            raise _ValidationError("Only demo tenants may be reset.")
        engine = get_registry().engine_for(g.tenant)
        sqlite_path = _sqlite_path(engine)
        if sqlite_path is not None and not sqlite_path.is_file():
            raise _ValidationError("Tenant database file is missing.")
        _storage_path(tenant_upload_root())
        return seed_demo(reset=True, confirmation=confirmation)


def _redacted_database(uri: str) -> str:
    try:
        url = make_url(uri)
        # Redact ALL query values: connection strings use many secret-key names.
        return url.set(username="redacted" if url.username is not None else None,
                       password="redacted" if url.password is not None else None,
                       query={key: "redacted" for key in url.query}).render_as_string(hide_password=True)
    except Exception:
        return "Unavailable"


def _display_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    return {key: ("redacted" if any(part in key.upper() for part in ("PASSWORD", "SECRET", "TOKEN", "USERNAME", "API_KEY")) else _plain(value))
            for key, value in settings.items()}


@contextmanager
def _inspection_connection(engine) -> Generator[Any, None, None]:
    """Inspect without sessions; SQLite mode=ro cannot create a missing file."""
    path = _sqlite_path(engine)
    if path is not None:
        if not path.is_file():
            raise _ValidationError("Tenant database file is missing.")
        readonly = create_engine(URL.create("sqlite+pysqlite", database=f"file:{path.as_posix()}",
                                           query={"mode": "ro", "uri": "true"}), poolclass=NullPool)
        try:
            with readonly.connect() as connection:
                yield connection
        finally:
            readonly.dispose()
    else:
        with engine.connect() as connection, connection.begin():
            if engine.url.get_backend_name() == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
            yield connection


def fleet_rows() -> list[dict[str, Any]]:
    """One failure-isolated, credential-redacted inventory row per tenant."""
    app = current_app._get_current_object()
    registry = get_registry()
    try:
        heads = set(ScriptDirectory(MIGRATIONS).get_heads())
    except Exception:
        heads = None
    rows = []
    for tenant in registry.tenants.values():
        # Keep editable content available even if engine binding/inspection fails.
        settings = {key: app.config[key] for key in (*IDENTITY_FIELDS, *FEATURE_FLAGS,
                    "DEMO_TENANT", "CANONICAL_ORIGIN", "SITE_PRESET", "PUBLIC_SITE_PRESET")
                    if key in app.config}
        settings.update(_plain(tenant.settings))
        settings["PUBLIC_PAGES_CONFIG"] = _plain(tenant.settings.get("PUBLIC_PAGES_CONFIG", {}))
        preset = settings.get("SITE_PRESET", settings.get("PUBLIC_SITE_PRESET", DEFAULT_PRESET))
        row = {
            "tenant": tenant, "settings": _display_settings(settings), "canonical_url": settings.get("CANONICAL_ORIGIN", ""),
            "preset": preset,
            "database": _redacted_database(tenant.database_uri), "backend": "unknown",
            "database_bytes": None, "revision": None, "migration_status": "unknown",
            "counts": {name: None for name in _COUNTED_TABLES},
            "upload_root": None, "upload_files": 0, "upload_bytes": 0,
            "theme": None, "error": None,
        }
        try:
            with operator_context(tenant, registry=registry) as target:
                settings = current_tenant_settings()
                row["settings"] = _display_settings(settings)
                row["settings"]["PUBLIC_PAGES_CONFIG"] = _plain(tenant.settings.get("PUBLIC_PAGES_CONFIG", {}))
                public_settings = {**app.config, **settings}
                row["preset"] = public_settings.get("SITE_PRESET", public_settings.get("PUBLIC_SITE_PRESET", DEFAULT_PRESET))
                row["canonical_url"] = settings.get("CANONICAL_ORIGIN", "")
                uploads = _storage_path(tenant_upload_root())
                row["upload_root"] = str(uploads)
                # Validate the path before the theme service reads tenant state.
                _storage_path(Path(app.instance_path) / "theme.json" if target.slug == registry.default_slug else uploads.parent / "theme.json")
                row["theme"] = themes.get_active_slug(app)
                if uploads.exists():
                    for item in uploads.rglob("*"):
                        _storage_path(item)
                        if item.is_file():
                            row["upload_files"] += 1
                            row["upload_bytes"] += item.stat().st_size
                engine = get_registry().engine_for(target)
                row["backend"] = engine.url.get_backend_name()
                sqlite_path = _sqlite_path(engine)
                if sqlite_path is not None and sqlite_path.is_file():
                    row["database_bytes"] = sqlite_path.stat().st_size
                with _inspection_connection(engine) as connection:
                    tables = set(inspect(connection).get_table_names())
                    for name in _COUNTED_TABLES:
                        if name in tables:
                            row["counts"][name] = connection.execute(text(f'SELECT count(*) FROM "{name}"')).scalar_one()
                    revisions = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars()) if "alembic_version" in tables else set()
                    row["revision"] = ", ".join(sorted(revisions)) or None
                    row["migration_status"] = (
                        "unknown" if heads is None else "current" if revisions == heads else
                        "uninitialized" if not revisions else "pending"
                    )
                    if row["backend"] == "postgresql":
                        row["database_bytes"] = connection.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
                    if any(value is None for value in row["counts"].values()) or heads is None:
                        row["error"] = "Tenant schema or migration metadata is incomplete."
        except (Exception, SystemExit):
            row["error"] = "Tenant inspection failed; verify database and storage availability."
        rows.append(row)
    return rows
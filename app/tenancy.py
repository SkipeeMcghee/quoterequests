from __future__ import annotations

import json
import re
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, Response, current_app, g, has_request_context, request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool

from app.config import (
    DEFAULT_SITE_LOGO_PATH,
    SOCIAL_PLATFORM_ASSETS,
    TENANT_SETTING_KEYS,
    normalize_canonical_origin,
    normalize_static_asset_path,
    validate_tenant_settings,
)


def _freeze_settings(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_settings(item) for key, item in value.items()})
    return value


@dataclass(frozen=True)
class Tenant:
    slug: str
    hosts: tuple[str, ...]
    database_uri: str = field(repr=False)
    enabled: bool = True
    settings: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}), repr=False)


def normalize_host(host: str) -> str:
    if not host or any(char.isspace() or ord(char) < 33 for char in host):
        raise ValueError("Invalid tenant host.")
    if any(char in host for char in "/\\?#@"):
        raise ValueError("Invalid tenant host.")

    parsed = urlsplit(f"//{host}")
    hostname = parsed.hostname
    parsed.port  # Validate the optional port even though routing ignores it.
    if not hostname:
        raise ValueError("Invalid tenant host.")
    hostname = hostname.rstrip(".").encode("idna").decode("ascii").lower()

    try:
        return ip_address(hostname).compressed
    except ValueError:
        pass

    if hostname.startswith("www."):
        hostname = hostname[4:]
    if len(hostname) > 253 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in hostname.split(".")
    ):
        raise ValueError("Invalid tenant host.")
    return hostname


def _engine_options(database_uri: str) -> dict[str, object]:
    url = make_url(database_uri)
    options: dict[str, object] = {"pool_pre_ping": True, "pool_recycle": 1800}
    if not (url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:")):
        options.update(pool_size=2, max_overflow=0, pool_timeout=30)
    return options


class TenantRegistry:
    """Startup-loaded control data; never queries a customer session."""

    def __init__(self, tenants: list[Tenant], default_slug: str | None = None) -> None:
        self.tenants = MappingProxyType({tenant.slug: tenant for tenant in tenants})
        self.default_slug = default_slug
        self.engines: Mapping[str, Engine] = MappingProxyType({})
        self._hosts: dict[str, Tenant] = {}
        for tenant in tenants:
            for host in tenant.hosts:
                normalized = normalize_host(host)
                existing = self._hosts.get(normalized)
                if existing is not None and existing.slug != tenant.slug:
                    raise ValueError(f"Tenant host is assigned more than once: {normalized}")
                self._hosts[normalized] = tenant

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> TenantRegistry:
        configured = config.get("TENANTS")
        if configured is None and config.get("TENANTS_JSON"):
            configured = json.loads(str(config["TENANTS_JSON"]))
        if configured is None and config.get("TENANT_ALLOW_DEFAULT"):
            uri = config.get("SQLALCHEMY_DATABASE_URI")
            hosts = config.get("TENANT_DEFAULT_HOSTS")
            if not isinstance(uri, str) or not isinstance(hosts, (list, tuple)):
                raise ValueError("The default tenant requires a database URI and host list.")
            if not hosts or not all(isinstance(host, str) for host in hosts):
                raise ValueError("The default tenant requires a nonempty host list.")
            return cls([Tenant("default", tuple(hosts), uri)], default_slug="default")
        if not isinstance(configured, Mapping) or not configured:
            raise ValueError("Configure a nonempty TENANTS mapping or TENANTS_JSON.")

        tenants: list[Tenant] = []
        for slug, settings in configured.items():
            if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", slug):
                raise ValueError("Tenant slugs must contain lowercase letters, digits, '_' or '-'.")
            if not isinstance(settings, Mapping):
                raise ValueError(f"Invalid settings for tenant {slug}.")
            hosts = settings.get("hosts")
            uri = settings.get("database_uri")
            enabled = settings.get("enabled", True)
            if not isinstance(hosts, (list, tuple)) or not hosts or not all(
                isinstance(host, str) for host in hosts
            ):
                raise ValueError(f"Tenant {slug} requires a nonempty host list.")
            if not isinstance(uri, str) or not uri:
                raise ValueError(f"Tenant {slug} requires a database URI.")
            if not isinstance(enabled, bool):
                raise ValueError(f"Tenant {slug} enabled must be a boolean.")
            overrides = settings.get("settings", {})
            if not isinstance(overrides, Mapping):
                raise ValueError(f"Tenant {slug} settings must be a mapping.")
            validate_tenant_settings(overrides)
            tenants.append(Tenant(slug, tuple(hosts), uri, enabled, _freeze_settings(overrides)))
        return cls(tenants)

    def resolve(self, host: str) -> Tenant | None:
        tenant = self._hosts.get(normalize_host(host))
        return tenant if tenant is not None and tenant.enabled else None

    def engine_for(self, tenant: Tenant) -> Engine:
        if self.tenants.get(tenant.slug) is not tenant or not tenant.enabled:
            raise RuntimeError("Tenant is not enabled in this registry.")
        return self.engines[tenant.slug]

    def configure_engines(self, app: Flask) -> None:
        if uri := app.config.get("SQLALCHEMY_DATABASE_URI"):
            app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
                **_engine_options(uri),
                **app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {}),
            }

    def bind_engines(self, app: Flask, default_engine: Engine) -> None:
        engines: dict[str, Engine] = {}
        for tenant in self.tenants.values():
            if not tenant.enabled:
                continue
            if tenant.slug == self.default_slug:
                engines[tenant.slug] = default_engine
                continue
            url = make_url(tenant.database_uri)
            options = _engine_options(tenant.database_uri)
            if url.get_backend_name() == "sqlite":
                options["connect_args"] = {"check_same_thread": False}
                if url.database in (None, "", ":memory:"):
                    options["poolclass"] = StaticPool
                else:
                    is_uri = bool(url.query.get("uri"))
                    path = url.database[5:] if is_uri else url.database
                    if not Path(path).is_absolute():
                        path = str(Path(app.instance_path) / path)
                        url = url.set(database=f"file:{path}" if is_uri else path)
            engines[tenant.slug] = create_engine(url, **options)
        self.engines = MappingProxyType(engines)


def get_registry() -> TenantRegistry:
    return current_app.extensions["tenancy"]


def get_current_tenant() -> Tenant:
    tenant = getattr(g, "tenant", None)
    if tenant is not None:
        return tenant
    registry = get_registry()
    if registry.default_slug is not None:
        if not has_request_context():
            return registry.tenants[registry.default_slug]
        # Bare test_request_context does not execute before_request hooks.
        tenant = registry.resolve(request.host)
        if tenant is not None:
            g.tenant = tenant
            return tenant
    raise RuntimeError("An active tenant is required before accessing a customer database.")


def current_tenant_settings() -> Mapping[str, Any]:
    tenant = get_current_tenant()
    overrides = tenant.settings
    settings = {key: current_app.config[key] for key in TENANT_SETTING_KEYS if key in current_app.config}
    settings.update(overrides)

    name = overrides.get("BUSINESS_NAME", overrides.get("COMPANY_NAME", settings.get("BUSINESS_NAME", "Service Company")))
    settings.update(BUSINESS_NAME=name, COMPANY_NAME=name)
    currency = overrides.get(
        "STAFF_COMPENSATION_CURRENCY",
        overrides.get("COMPENSATION_CURRENCY", settings.get("STAFF_COMPENSATION_CURRENCY", "USD")),
    )
    settings["STAFF_COMPENSATION_CURRENCY"] = settings["COMPENSATION_CURRENCY"] = (currency.strip() or "USD").upper()
    if "DEFAULT_FROM_EMAIL" not in overrides and "BUSINESS_EMAIL" in overrides:
        settings["DEFAULT_FROM_EMAIL"] = overrides["BUSINESS_EMAIL"]
    if "EMAIL_FROM_NAME" not in overrides and ("BUSINESS_NAME" in overrides or "COMPANY_NAME" in overrides):
        settings["EMAIL_FROM_NAME"] = name

    logo = {}
    for source in (current_app.config, overrides):
        logo.update(source.get("SITE_LOGO", {}))
        for key, field_name in (("SITE_LOGO_PATH", "path"), ("SITE_LOGO_ALT", "alt")):
            if key in source:
                logo[field_name] = source[key]
    logo["path"] = normalize_static_asset_path(logo.get("path", ""), DEFAULT_SITE_LOGO_PATH)
    settings.update(SITE_LOGO=logo, SITE_LOGO_PATH=logo["path"], SITE_LOGO_ALT=logo.get("alt", ""))

    links = {}
    for source in (current_app.config, overrides):
        for platform, link in source.get("SOCIAL_LINKS", {}).items():
            if isinstance(link, Mapping):
                links[platform] = {**SOCIAL_PLATFORM_ASSETS.get(platform, {}), **links.get(platform, {}), **link}
        for platform, assets in SOCIAL_PLATFORM_ASSETS.items():
            prefix = f"SOCIAL_{platform.upper()}"
            for suffix, field_name in (("ENABLED", "enabled"), ("URL", "url")):
                if f"{prefix}_{suffix}" in source:
                    links.setdefault(platform, dict(assets))[field_name] = source[f"{prefix}_{suffix}"]
    for platform in SOCIAL_PLATFORM_ASSETS:
        prefix = f"SOCIAL_{platform.upper()}"
        settings[f"{prefix}_ENABLED"] = links.get(platform, {}).get("enabled", False)
        settings[f"{prefix}_URL"] = links.get(platform, {}).get("url", "")
    settings["SOCIAL_LINKS"] = links

    origin = settings.get("CANONICAL_ORIGIN", "")
    if not origin and get_registry().default_slug != tenant.slug:
        origin = f"https://{tenant.hosts[0]}"
    settings["CANONICAL_ORIGIN"] = normalize_canonical_origin(origin)
    return _freeze_settings(settings)


def tenant_config(key: str, default: Any = None) -> Any:
    return current_tenant_settings().get(key, default)


@contextmanager
def tenant_context(slug: str) -> Generator[Tenant]:
    """Select a tenant for non-HTTP work in a fresh application context."""

    from app.extensions import db

    if has_request_context() or getattr(g, "tenant", None) is not None or db.session.registry.has():
        raise RuntimeError("tenant_context requires a fresh, non-request application context.")
    tenant = get_registry().tenants.get(slug)
    if tenant is None or not tenant.enabled:
        raise ValueError("Unknown or disabled tenant.")
    g.tenant = tenant
    try:
        yield tenant
    finally:
        db.session.remove()
        g.pop("tenant", None)


def register_tenancy(app: Flask) -> None:
    registry = TenantRegistry.from_config(app.config)
    registry.configure_engines(app)
    app.extensions["tenancy"] = registry

    @app.before_request
    def resolve_tenant():
        g.pop("tenant", None)
        g.pop("_login_user", None)
        try:
            tenant = registry.resolve(request.host)
        except (ValueError, UnicodeError):
            app.logger.warning("Rejected malformed tenant host.")
            return Response("Invalid host.", status=400, mimetype="text/plain")
        if tenant is None:
            app.logger.warning("Rejected unknown or disabled tenant host.")
            return Response("Unknown host.", status=404, mimetype="text/plain")
        g.tenant = tenant

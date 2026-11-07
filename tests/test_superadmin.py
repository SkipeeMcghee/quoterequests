"""Platform control integration/security tests; use only temporary tenant storage."""

import hashlib
import json
import logging
import re
import sqlite3
import tarfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from alembic.script import ScriptDirectory
from flask import jsonify, session
from flask_login import current_user, login_required
from sqlalchemy import event

from app import create_app
from app.extensions import csrf, db
from app.models import Customer, User
from app.services import rate_limit
from app.tenancy import current_tenant_settings, get_current_tenant, tenant_context


CONTROL = "control.platform.test"
BASE = f"http://{CONTROL}"
PATH = "/platform/control"
PASSWORD = "fleet-password"
ALPHA = "alpha.platform.test"
BETA = "beta.platform.test"


@pytest.fixture(autouse=True)
def clean_platform_limits():
    rate_limit.reset_all()
    yield
    rate_limit.reset_all()


@pytest.fixture()
def platform_factory(tmp_path):
    apps = []

    def factory(**overrides):
        config = {
            "SECRET_KEY": "platform-tests-independent-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite+pysqlite:///:memory:",
            "TENANTS": {},
            "TENANTS_JSON": "",
            "TENANT_ALLOW_DEFAULT": False,
            "TENANT_REGISTRY_FILE": str(tmp_path / "registry.json"),
            "SUPERADMIN_PASSWORD": PASSWORD,
            "SUPERADMIN_HOST": CONTROL,
            "SUPERADMIN_PATH": PATH,
            "SUPERADMIN_HANDOFF_TTL_SECONDS": 60,
            "WTF_CSRF_ENABLED": False,
            "WTF_CSRF_SSL_STRICT": False,
            "TRUST_PROXY": False,
            "RATE_LIMIT_ENABLED": False,
            "RATE_LIMIT_LOGIN_REQUESTS": 100,
            "RATE_LIMIT_LOGIN_WINDOW_SECONDS": 300,
            "EMAIL_ENABLED": False,
            "ERROR_WEBHOOK_URL": "",
            "RECAPTCHA_ENABLED": False,
            "RECAPTCHA_SITE_KEY": "",
            "RECAPTCHA_SECRET_KEY": "",
            "CANONICAL_ORIGIN": "",
            "UPLOAD_FOLDER": str(tmp_path / "unused-uploads"),
        }
        config.update(overrides)
        # Import through create_app first: superadmin operations imports app.cli.
        app = create_app("testing", config)
        app.instance_path = str(tmp_path / "instance")
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
        apps.append(app)

        @app.get("/__platform_test_tenant")
        def tenant_probe():
            settings = current_tenant_settings()
            return jsonify(
                slug=get_current_tenant().slug,
                business=settings["BUSINESS_NAME"],
                origin=settings["CANONICAL_ORIGIN"],
                services=settings["ENABLE_SERVICES"],
                gallery=settings["ENABLE_GALLERY"],
                calendar=settings["ENABLE_CALENDAR"],
            )

        @app.get("/__platform_test_identity")
        @login_required
        def identity_probe():
            return jsonify(identity=current_user.get_id(), email=current_user.email,
                           platform_proof=session.get("_superadmin_authenticated"),
                           impersonating=session.get("_superadmin_impersonating"))

        return app

    yield factory
    for app in reversed(apps):
        with app.app_context():
            db.session.remove()
            for engine in set(db.engines.values()) | set(app.extensions["tenancy"].engines.values()):
                engine.dispose()


@pytest.fixture()
def platform_app(platform_factory):
    return platform_factory()


def html_token(response):
    assert response.status_code == 200
    match = re.search(r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)',
                      response.get_data(as_text=True))
    assert match, "The real form must expose a CSRF token."
    return match.group(1)


def post_action(client, app, action, **fields):
    data = {"action": action, **fields}
    path = app.config["SUPERADMIN_PATH"]
    if app.config["WTF_CSRF_ENABLED"]:
        data["csrf_token"] = html_token(client.get(path, base_url=BASE))
    return client.post(path, base_url=BASE, data=data)


def login(client, app):
    response = post_action(client, app, "login", password=app.config["SUPERADMIN_PASSWORD"])
    assert response.status_code == 302
    assert urlsplit(response.location).path.rstrip("/") == app.config["SUPERADMIN_PATH"]
    return response


def provision(client, app, slug="alpha", **fields):
    data = {
        "slug": slug,
        "domains": f"{slug}.platform.test",
        "BUSINESS_NAME": f"{slug.title()} Services",
        "admin_email": f"{slug}@example.test",
        "admin_password": f"{slug}-password",
        "ENABLE_SERVICES": "on",
        "ENABLE_GALLERY": "on",
    }
    data.update(fields)
    response = post_action(client, app, "create", **data)
    assert response.status_code == 302
    assert slug in app.extensions["tenancy"].tenants, response.get_data(as_text=True)
    return app.extensions["tenancy"].tenants[slug]


@pytest.fixture()
def fleet(platform_app):
    client = platform_app.test_client()
    login(client, platform_app)
    provision(client, platform_app, demo_tenant="on", seed_demo="on")
    provision(client, platform_app, "beta")
    return platform_app, client


def tenant_db(app, slug):
    return Path(app.instance_path) / "tenants" / slug / "tenant.sqlite3"


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def users(app, slug):
    with app.app_context(), tenant_context(slug):
        return [(user.id, user.email, user.password_hash, user.is_active)
                for user in User.query.order_by(User.id).all()]


def issue(client, app, slug="alpha"):
    response = post_action(client, app, "impersonate", slug=slug)
    assert response.status_code == 302
    target = urlsplit(response.location)
    assert target.scheme == "https"
    assert target.netloc == app.extensions["tenancy"].tenants[slug].hosts[0]
    assert target.path == "/admin/superadmin-handoff"
    token = parse_qs(target.query)["token"][0]
    assert token
    return response.location


def consume(client, target, host=None):
    parsed = urlsplit(target)
    return client.get(f"{parsed.path}?{parsed.query}",
                      base_url=f"https://{host or parsed.netloc}")


@pytest.mark.parametrize("password", [None, "", " ", "\t\n"])
def test_unset_or_blank_password_fails_closed_before_csrf_and_database(platform_factory, monkeypatch, password):
    app = platform_factory(SUPERADMIN_PASSWORD=password, WTF_CSRF_ENABLED=True)
    if password is None:
        app.config.pop("SUPERADMIN_PASSWORD")
    assert_boundary_closed(app, monkeypatch, CONTROL)


@pytest.mark.parametrize("host", ["unknown.platform.test", ALPHA, "control.platform.test.evil.test"])
def test_wrong_host_fails_closed_before_csrf_and_database(platform_app, monkeypatch, host):
    platform_app.config["WTF_CSRF_ENABLED"] = True
    assert_boundary_closed(platform_app, monkeypatch, host)


def assert_boundary_closed(app, monkeypatch, host):
    def forbidden(*args, **kwargs):
        raise AssertionError("Closed platform boundaries must not touch CSRF or a database.")

    monkeypatch.setattr(csrf, "protect", forbidden)
    with app.app_context():
        engines = set(db.engines.values()) | set(app.extensions["tenancy"].engines.values())
    for engine in engines:
        event.listen(engine, "before_cursor_execute", forbidden)
    try:
        client = app.test_client()
        for method in (client.get, client.post):
            for suffix in ("", "/", "/unknown"):
                response = method(app.config["SUPERADMIN_PATH"] + suffix, base_url=f"http://{host}")
                assert response.status_code == 404
        assert not Path(app.config["TENANT_REGISTRY_FILE"]).exists()
        assert not (Path(app.instance_path) / "tenants").exists()
    finally:
        for engine in engines:
            event.remove(engine, "before_cursor_execute", forbidden)


def test_login_page_bad_password_and_authenticated_dashboard(platform_app):
    client = platform_app.test_client()
    page = client.get(PATH, base_url=BASE)
    assert page.status_code == 200
    for header, value in {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                          "X-Robots-Tag": "noindex, nofollow", "X-Frame-Options": "DENY"}.items():
        assert page.headers[header] == value
    bad = post_action(client, platform_app, "login", password="wrong")
    assert bad.status_code == 401
    assert b"Invalid password" in bad.data
    login(client, platform_app)
    page = client.get(PATH, base_url=BASE)
    assert page.status_code == 200
    assert b"registry" in page.data.lower()
    assert PASSWORD.encode() not in page.data


def test_custom_control_path(platform_factory):
    app = platform_factory(SUPERADMIN_PATH="/operator/fleet")
    client = app.test_client()
    assert client.get("/operator/fleet", base_url=BASE).status_code == 200
    login(client, app)
    assert client.get("/operator/fleet/", base_url=BASE).status_code == 200
    assert client.get(PATH, base_url=BASE).status_code == 404


@pytest.mark.parametrize("action", ["create", "edit", "toggle", "upgrade", "backup", "reset_demo", "impersonate", "logout"])
def test_actions_require_independent_platform_login(platform_app, action):
    response = post_action(platform_app.test_client(), platform_app, action, slug="alpha")
    assert response.status_code == 401
    assert not Path(platform_app.config["TENANT_REGISTRY_FILE"]).exists()


def test_tenant_cookie_never_authenticates_control(fleet):
    app, operator = fleet
    client = app.test_client()
    assert client.post("/auth/login", base_url=f"http://{ALPHA}",
                       data={"email": "alpha@example.test", "password": "alpha-password"}).status_code == 302
    assert client.get("/__platform_test_identity", base_url=f"http://{ALPHA}").json["identity"] == "alpha:1"
    cookie = client.get_cookie(app.config["SESSION_COOKIE_NAME"], domain=ALPHA)
    client.set_cookie(app.config["SESSION_COOKIE_NAME"], cookie.value, domain=CONTROL)
    assert post_action(client, app, "toggle", slug="beta").status_code == 401
    assert app.extensions["tenancy"].tenants["beta"].enabled
    # Conversely, copying an operator cookie must not grant tenant authentication.
    cookie = operator.get_cookie(app.config["SESSION_COOKIE_NAME"], domain=CONTROL)
    stranger = app.test_client()
    stranger.set_cookie(app.config["SESSION_COOKIE_NAME"], cookie.value, domain=ALPHA)
    assert stranger.get("/__platform_test_identity", base_url=f"http://{ALPHA}").status_code == 302


def test_real_csrf_tokens_required_for_login_and_actions(platform_factory):
    app = platform_factory(WTF_CSRF_ENABLED=True)
    client = app.test_client()
    for data in ({"action": "login", "password": PASSWORD},
                 {"action": "login", "password": PASSWORD, "csrf_token": "invalid"}):
        assert client.post(PATH, base_url=BASE, data=data).status_code == 400
    login(client, app)
    for token in (None, "invalid"):
        data = {"action": "create", "slug": "alpha", "domains": ALPHA}
        if token is not None:
            data["csrf_token"] = token
        assert client.post(PATH, base_url=BASE, data=data).status_code == 400
    assert not Path(app.config["TENANT_REGISTRY_FILE"]).exists()
    provision(client, app)
    assert client.get("/", base_url=f"http://{ALPHA}").status_code == 200
    assert post_action(client, app, "toggle", slug="alpha").status_code == 302
    assert not app.extensions["tenancy"].tenants["alpha"].enabled


@pytest.mark.parametrize("csrf_enabled,expected", [(False, 401), (True, 400)])
def test_login_limit_precedes_csrf_and_ignores_raw_forwarded_for(platform_factory, csrf_enabled, expected):
    app = platform_factory(WTF_CSRF_ENABLED=csrf_enabled, RATE_LIMIT_LOGIN_REQUESTS=2)
    client = app.test_client()
    for index in range(2):
        response = client.post(PATH, base_url=BASE,
                               data={"action": "login", "password": "wrong", "csrf_token": "invalid"},
                               headers={"X-Forwarded-For": f"198.51.100.{index + 1}"},
                               environ_overrides={"REMOTE_ADDR": "203.0.113.1"})
        assert response.status_code == expected
    limited = client.post(PATH, base_url=BASE, data={"action": "login"},
                          headers={"X-Forwarded-For": "198.51.100.99"},
                          environ_overrides={"REMOTE_ADDR": "203.0.113.1"})
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "300"
    other = client.post(PATH, base_url=BASE, data={"action": "login", "password": "wrong"},
                        environ_overrides={"REMOTE_ADDR": "203.0.113.2"})
    assert other.status_code == expected


@pytest.mark.parametrize("key,replacement", [("SUPERADMIN_PASSWORD", "rotated-fleet-password"),
                                            ("SECRET_KEY", "rotated-independent-key")])
def test_rotating_either_key_invalidates_operator_session_and_handoff(fleet, key, replacement):
    app, client = fleet
    target = issue(client, app)
    app.config[key] = replacement
    assert post_action(client, app, "toggle", slug="beta").status_code == 401
    assert consume(app.test_client(), target).status_code == 403
    assert app.extensions["tenancy"].tenants["beta"].enabled
    login(client, app)
    assert post_action(client, app, "toggle", slug="beta").status_code == 302
    assert not app.extensions["tenancy"].tenants["beta"].enabled


def test_provision_migrates_counts_uploads_and_domain_immediately(platform_app):
    from app.cli import MIGRATIONS
    from app.superadmin import operations

    client = platform_app.test_client()
    assert not platform_app.extensions["tenancy"].tenants
    login(client, platform_app)
    tenant = provision(client, platform_app, domains=f"WWW.ALPHA.PLATFORM.TEST:443, alias.platform.test",
                       demo_tenant="on", seed_demo="on")
    records = json.loads(Path(platform_app.config["TENANT_REGISTRY_FILE"]).read_text())
    assert records["alpha"]["hosts"] == [ALPHA, "alias.platform.test"]
    assert records["alpha"]["settings"]["DEMO_TENANT"] is True
    assert records["alpha"]["settings"]["EMAIL_ENABLED"] is False
    assert tenant_db(platform_app, "alpha").is_file()
    uploads = Path(platform_app.instance_path) / "tenants" / "alpha" / "uploads"
    assert all((uploads / name).is_dir() for name in ("quote_requests", "customers", "gallery"))
    with sqlite3.connect(tenant_db(platform_app, "alpha")) as connection:
        assert {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")} == set(ScriptDirectory(MIGRATIONS).get_heads())
    with platform_app.app_context():
        row, = operations.fleet_rows()
    assert row["tenant"].slug == tenant.slug
    assert row["error"] is None
    assert row["migration_status"] == "current"
    # Migration seeds ten services; demo reuses Window Cleaning and adds two.
    assert row["counts"] == {"users": 1, "quote_requests": 7, "customers": 2,
                             "service_options": 12, "gallery_items": 1}
    for host in (ALPHA, "alias.platform.test"):
        assert client.get("/", base_url=f"http://{host}").status_code == 200
        assert client.get("/__platform_test_tenant", base_url=f"http://{host}").json["business"] == "Alpha Services"
    assert users(platform_app, "alpha")[0][1] == "alpha@example.test"


def test_edits_and_toggle_are_live_in_this_and_second_app(fleet, platform_factory):
    app, client = fleet
    second = platform_factory()
    observer = second.test_client()
    assert observer.get("/__platform_test_tenant", base_url=f"http://{ALPHA}").json["business"] == "Alpha Services"
    beta_before = checksum(tenant_db(app, "beta"))
    response = post_action(client, app, "edit", slug="alpha", domains="renamed.platform.test",
                           BUSINESS_NAME="Renamed Fleet Business", ENABLE_CALENDAR="on")
    assert response.status_code == 302
    for browser in (client, observer):
        assert browser.get("/", base_url=f"http://{ALPHA}").status_code == 404
        payload = browser.get("/__platform_test_tenant", base_url="http://renamed.platform.test").json
        assert payload == {"slug": "alpha", "business": "Renamed Fleet Business",
                           "origin": "https://renamed.platform.test", "services": False,
                           "gallery": False, "calendar": True}
    assert post_action(client, app, "toggle", slug="alpha").status_code == 302
    for browser in (client, observer):
        assert browser.get("/", base_url="http://renamed.platform.test").status_code == 404
    assert "alpha" not in second.extensions["tenancy"].engines
    assert post_action(client, app, "toggle", slug="alpha").status_code == 302
    for browser in (client, observer):
        assert browser.get("/", base_url="http://renamed.platform.test").status_code == 200
    assert checksum(tenant_db(app, "beta")) == beta_before


def test_second_app_started_empty_refreshes_after_provision(platform_app, platform_factory):
    second = platform_factory()
    assert not second.extensions["tenancy"].tenants
    client = platform_app.test_client()
    login(client, platform_app)
    provision(client, platform_app)
    assert second.test_client().get("/__platform_test_tenant", base_url=f"http://{ALPHA}").json["slug"] == "alpha"


def test_upgrade_and_real_backup_leave_beta_unchanged(fleet):
    app, client = fleet
    beta_before, beta_users = checksum(tenant_db(app, "beta")), users(app, "beta")
    uploads = Path(app.instance_path) / "tenants" / "alpha" / "uploads"
    (uploads / "gallery" / "example.txt").write_text("alpha-only artifact", encoding="utf-8")
    theme = uploads.parent / "theme.json"
    theme.write_text('{"theme": "test-backup"}', encoding="utf-8")
    assert post_action(client, app, "upgrade", slug="alpha").status_code == 302
    assert post_action(client, app, "backup", slug="alpha").status_code == 302
    manifests = list((Path(app.instance_path) / "platform-backups" / "alpha").glob("*/manifest.json"))
    assert len(manifests) == 1
    artifact = manifests[0].parent
    manifest = json.loads(manifests[0].read_text())
    assert manifest["tenant"] == "alpha"
    assert manifest["row_counts"]["users"] == 1
    assert manifest["row_counts"]["quote_requests"] == 7
    for key in ("database", "uploads", "theme"):
        entry = manifest[key]
        assert checksum(artifact / entry["file"]) == entry["sha256"]
    with tarfile.open(artifact / manifest["uploads"]["file"], "r:gz") as archive:
        assert archive.getnames() == ["gallery/example.txt"]
        assert archive.extractfile("gallery/example.txt").read() == b"alpha-only artifact"
    with sqlite3.connect(artifact / manifest["database"]["file"]) as connection:
        assert connection.execute("SELECT email FROM users").fetchall() == [("alpha@example.test",)]
    assert (artifact / "theme.json").read_bytes() == theme.read_bytes()
    assert checksum(tenant_db(app, "beta")) == beta_before
    assert users(app, "beta") == beta_users


def test_guarded_demo_reset_preserves_admins_and_other_tenant(fleet):
    app, client = fleet
    alpha_users, beta_users = users(app, "alpha"), users(app, "beta")
    with app.app_context(), tenant_context("alpha"):
        db.session.add(Customer(primary_name="Temporary business record", primary_city="Test City"))
        db.session.commit()
    alpha_before, beta_before = checksum(tenant_db(app, "alpha")), checksum(tenant_db(app, "beta"))
    for slug, confirmation in (("alpha", ""), ("alpha", "ALPHA"), ("beta", "beta")):
        assert post_action(client, app, "reset_demo", slug=slug, confirmation=confirmation).status_code == 302
        assert checksum(tenant_db(app, "alpha")) == alpha_before
        assert checksum(tenant_db(app, "beta")) == beta_before
    assert post_action(client, app, "reset_demo", slug="alpha", confirmation="alpha").status_code == 302
    with app.app_context(), tenant_context("alpha"):
        assert Customer.query.count() == 2
        assert Customer.query.filter_by(primary_name="Temporary business record").first() is None
    assert users(app, "alpha") == alpha_users
    assert users(app, "beta") == beta_users
    assert checksum(tenant_db(app, "beta")) == beta_before


def test_handoff_wrong_tenant_non_consuming_and_durable_single_use(fleet, platform_factory):
    app, client = fleet
    target = issue(client, app)
    stranger = app.test_client()
    assert consume(stranger, target, BETA).status_code == 403
    second = platform_factory()
    assert second.instance_path == app.instance_path
    recipient = second.test_client()
    response = consume(recipient, target)
    assert response.status_code == 302
    assert urlsplit(response.location).path == "/admin/"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert recipient.get("/__platform_test_identity", base_url=f"https://{ALPHA}").json == {
        "identity": "alpha:1", "email": "alpha@example.test", "platform_proof": None, "impersonating": "alpha"}
    assert consume(app.test_client(), target).status_code == 403
    assert consume(second.test_client(), target).status_code == 403
    with sqlite3.connect(Path(app.instance_path) / "platform-control" / "handoffs.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM handoffs").fetchone()[0] == 0


def test_impersonation_banner_and_exit_remove_identity_not_create_master_key(fleet):
    app, client = fleet
    recipient = app.test_client()
    assert consume(recipient, issue(client, app)).status_code == 302
    page = recipient.get("/admin/", base_url=f"https://{ALPHA}")
    assert page.status_code == 200
    assert b"Exit Impersonation" in page.data
    assert b"Alpha Services" in page.data
    response = recipient.post("/admin/exit-impersonation", base_url=f"https://{ALPHA}")
    assert response.status_code == 302
    assert urlsplit(response.location).path == "/admin"
    assert recipient.get("/__platform_test_identity", base_url=f"https://{ALPHA}").status_code == 302
    cookie = recipient.get_cookie(app.config["SESSION_COOKIE_NAME"], domain=ALPHA)
    if cookie is not None:
        recipient.set_cookie(app.config["SESSION_COOKIE_NAME"], cookie.value, domain=CONTROL)
    assert post_action(recipient, app, "toggle", slug="beta").status_code == 401
    assert recipient.post("/admin/exit-impersonation", base_url=f"https://{ALPHA}").status_code == 403
    assert app.extensions["tenancy"].tenants["beta"].enabled


def test_handoff_persistent_expiry_even_with_fresh_signature(fleet, monkeypatch):
    from app.superadmin import routes
    from itsdangerous.timed import TimestampSigner

    app, client = fleet
    target = issue(client, app)
    now = routes.time.time()
    # time is a shared module: keep the signature young to isolate SQLite expiry.
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: int(now))
    monkeypatch.setattr(routes.time, "time", lambda: now + app.config["SUPERADMIN_HANDOFF_TTL_SECONDS"] + 1)
    assert consume(app.test_client(), target).status_code == 403


def test_handoff_signature_age_even_when_persistent_nonce_is_unexpired(fleet, monkeypatch):
    import itsdangerous.timed as timed

    app, client = fleet
    target = issue(client, app)
    future = timed.time.time() + app.config["SUPERADMIN_HANDOFF_TTL_SECONDS"] + 2
    path = Path(app.instance_path) / "platform-control" / "handoffs.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE handoffs SET expires = ?", (future + 3600,))
    monkeypatch.setattr(timed.time, "time", lambda: future)
    assert consume(app.test_client(), target).status_code == 403
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM handoffs").fetchone()[0] == 1


def test_tampered_handoff_is_rejected_without_consuming_original(fleet):
    app, client = fleet
    target = issue(client, app)
    parsed = urlsplit(target)
    token = parse_qs(parsed.query)["token"][0]
    payload, timestamp, signature = token.rsplit(".", 2)
    tampered = f"{payload}.{timestamp}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    recipient = app.test_client()
    assert recipient.get(parsed.path, base_url=f"https://{ALPHA}", query_string={"token": tampered}).status_code == 403
    assert recipient.get("/__platform_test_identity", base_url=f"https://{ALPHA}").status_code == 302
    assert consume(recipient, target).status_code == 302


def test_disabled_or_adminless_tenant_cannot_be_impersonated(platform_app):
    client = platform_app.test_client()
    login(client, platform_app)
    provision(client, platform_app, admin_email="", admin_password="")
    response = post_action(client, platform_app, "impersonate", slug="alpha")
    assert urlsplit(response.location).path.rstrip("/") == PATH
    assert not (Path(platform_app.instance_path) / "platform-control" / "handoffs.sqlite3").exists()
    provision(client, platform_app, "beta")
    post_action(client, platform_app, "toggle", slug="beta")
    response = post_action(client, platform_app, "impersonate", slug="beta")
    assert urlsplit(response.location).path.rstrip("/") == PATH


@pytest.mark.parametrize("fields", [
    {"slug": "alpha", "domains": "duplicate.platform.test"},
    {"slug": "gamma", "domains": "WWW.ALPHA.PLATFORM.TEST:443"},
    {"slug": "gamma", "domains": CONTROL},
    {"slug": "../escape", "domains": "escape.platform.test"},
    {"slug": "..\\escape", "domains": "escape.platform.test"},
    {"slug": "gamma", "domains": "https://invalid.platform.test/path"},
    {"slug": "gamma", "domains": ""},
    {"slug": "gamma", "domains": "gamma.platform.test", "seed_demo": "on"},
])
def test_invalid_provisioning_preserves_registry_and_existing_databases(fleet, fields):
    app, client = fleet
    path = Path(app.config["TENANT_REGISTRY_FILE"])
    before = path.read_bytes()
    hashes = {slug: checksum(tenant_db(app, slug)) for slug in ("alpha", "beta")}
    response = post_action(client, app, "create", **fields)
    assert response.status_code == 302
    assert path.read_bytes() == before
    assert set(app.extensions["tenancy"].tenants) == {"alpha", "beta"}
    assert {slug: checksum(tenant_db(app, slug)) for slug in hashes} == hashes
    assert not (Path(app.instance_path) / "tenants" / "gamma").exists()
    assert not (Path(app.instance_path) / "escape").exists()
    assert not path.with_name(path.name + ".lock").exists()


def test_database_alias_cannot_provision_over_existing_tenant(fleet):
    app, client = fleet
    path = Path(app.config["TENANT_REGISTRY_FILE"])
    before, alpha_before = path.read_bytes(), checksum(tenant_db(app, "alpha"))
    response = post_action(client, app, "create", slug="gamma", domains="gamma.platform.test",
                           database_uri=f"sqlite:///{tenant_db(app, 'alpha')}")
    assert response.status_code == 302
    assert path.read_bytes() == before
    assert checksum(tenant_db(app, "alpha")) == alpha_before
    assert "gamma" not in app.extensions["tenancy"].tenants


def test_static_tenants_are_read_only_but_operational(platform_factory, tmp_path):
    from app.superadmin import operations

    database = tmp_path / "static.sqlite3"
    app = platform_factory(TENANTS={"static": {"hosts": ["static.platform.test"],
                                               "database_uri": f"sqlite:///{database}",
                                               "settings": {"BUSINESS_NAME": "Static Business"}}})
    with app.app_context():
        operations.migrate_tenant(app.extensions["tenancy"].tenants["static"])
    client = app.test_client()
    login(client, app)
    before = checksum(database)
    for action in ("edit", "toggle"):
        assert post_action(client, app, action, slug="static", BUSINESS_NAME="Not Allowed").status_code == 302
        tenant = app.extensions["tenancy"].tenants["static"]
        assert tenant.enabled and tenant.settings["BUSINESS_NAME"] == "Static Business"
    assert not Path(app.config["TENANT_REGISTRY_FILE"]).exists()
    assert checksum(database) == before
    assert client.get("/", base_url="http://static.platform.test").status_code == 200
    assert post_action(client, app, "upgrade", slug="static").status_code == 302
    assert post_action(client, app, "backup", slug="static").status_code == 302
    assert list((Path(app.instance_path) / "platform-backups" / "static").glob("*/manifest.json"))


def test_audit_records_actions_outcomes_targets_without_secrets(platform_app, caplog):
    app = platform_app
    # Real operator migrations must preserve existing structured audit handlers.
    caplog.set_level(logging.INFO, logger=app.logger.name)
    client = app.test_client()
    assert post_action(client, app, "toggle", slug="alpha").status_code == 401
    login(client, app)
    provision(client, app)
    assert post_action(client, app, "upgrade", slug="alpha").status_code == 302
    assert post_action(client, app, "backup", slug="alpha").status_code == 302
    assert post_action(client, app, "reset_demo", slug="alpha", confirmation="alpha").status_code == 302
    target = issue(client, app)
    recipient = app.test_client()
    assert consume(recipient, target).status_code == 302
    assert consume(app.test_client(), target).status_code == 403
    assert recipient.post("/admin/exit-impersonation", base_url=f"https://{ALPHA}").status_code == 302
    assert post_action(client, app, "unknown").status_code == 400
    assert post_action(client, app, "logout").status_code == 302
    records = [record for record in caplog.records if getattr(record, "actor", None) == "superadmin"]
    events = {(record.event, record.target_tenant, record.outcome) for record in records}
    assert {
        ("superadmin.toggle", None, "unauthenticated"),
        ("superadmin.login", None, "success"),
        ("superadmin.create", "alpha", "success"),
        ("superadmin.upgrade", "alpha", "success"),
        ("superadmin.backup", "alpha", "success"),
        ("superadmin.reset_demo", "alpha", "failed"),
        ("superadmin.impersonate", "alpha", "issued"),
        ("superadmin.impersonate", "alpha", "consumed"),
        ("superadmin.impersonate", "alpha", "rejected"),
        ("superadmin.exit_impersonation", "alpha", "success"),
        ("superadmin.unknown", None, "rejected"),
        ("superadmin.logout", None, "success"),
    } <= events
    text = "\n".join(record.getMessage() for record in records)
    assert PASSWORD not in text
    assert "alpha-password" not in text
    assert parse_qs(urlsplit(target).query)["token"][0] not in text
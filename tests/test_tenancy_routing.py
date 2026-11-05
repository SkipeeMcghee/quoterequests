from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs

import pytest
from flask import g, jsonify, request as flask_request
from flask_login import current_user, login_required
from PIL import Image
from sqlalchemy import event, text
from sqlalchemy.exc import InvalidRequestError
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import BadRequest

from app import create_app
from app.extensions import csrf, db
from app.models import Appointment, Customer, CustomerPhoto, GalleryItem, QuoteRequest, RequestPhoto, ServiceOption, User
from app.services import email_hooks, media, rate_limit, recaptcha, themes, uploads
from app.tenancy import (
    TenantRegistry,
    current_tenant_settings,
    get_current_tenant,
    normalize_host,
    tenant_config,
    tenant_context,
    tenant_upload_root,
)


ALPHA = "alpha.example.test"
BETA = "beta.example.test"


@pytest.fixture()
def tenant_app(tmp_path, request):
    settings = getattr(request, "param", {})
    app = create_app("testing", {
        "SECRET_KEY": "tenant-routing-test-key",
        "SQLALCHEMY_DATABASE_URI": "sqlite+pysqlite:///:memory:",
        "TENANTS_JSON": "",
        "TENANTS": {
            slug: {
                "hosts": [host],
                "database_uri": f"sqlite+pysqlite:///{tmp_path / (slug + '.db')}",
                "settings": settings.get(slug, {}),
            }
            for slug, host in (("alpha", ALPHA), ("beta", BETA))
        } | {
            "disabled": {
                "hosts": ["disabled.example.test"],
                "database_uri": "sqlite+pysqlite:///:memory:",
                "enabled": False,
            },
        },
        "TRUST_PROXY": True,
        "EMAIL_ENABLED": False,
        "RECAPTCHA_ENABLED": False,
        "CANONICAL_ORIGIN": "",
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
    })
    app.instance_path = str(tmp_path / "instance")
    registry = app.extensions["tenancy"]
    for slug in ("alpha", "beta"):
        with app.app_context(), tenant_context(slug) as tenant:
            db.metadata.create_all(bind=registry.engine_for(tenant))
            user = User(email=f"{slug}@example.test")
            user.set_password(f"{slug}-password")
            customer = Customer(primary_name=f"{slug} customer", primary_city="Test City")
            db.session.add_all([user, customer])
            if tenant.settings:
                db.session.add_all([
                    ServiceOption(name=f"{slug} cleaning", display_order=0, is_active=True),
                    GalleryItem(title=f"{slug} gallery", image_path="assets/example.png", is_active=True),
                ])
            db.session.commit()
            assert user.id == customer.id == 1

    @app.get("/__tenant")
    def tenant_probe():
        customer = db.session.get(Customer, 1)
        return jsonify(
            tenant=g.tenant.slug,
            customer=customer.primary_name,
            count=db.session.execute(text("select count(*) from customers")).scalar_one(),
        )

    @app.get("/__protected")
    @login_required
    def protected_probe():
        return jsonify(identity=current_user.get_id(), email=current_user.email)

    @app.post("/__customer")
    def update_customer():
        customer = db.session.get(Customer, 1)
        customer.primary_name = flask_request.form["name"]
        db.session.commit()
        return "", 204

    @app.post("/__uncommitted")
    def uncommitted_customer():
        db.session.add(Customer(primary_name="discard me", primary_city="Test City"))
        db.session.flush()
        return "", 204

    rate_limit.reset_all()
    try:
        yield app
    finally:
        rate_limit.reset_all()
        with app.app_context():
            db.session.remove()
            for engine in set(db.engines.values()) | set(registry.engines.values()):
                engine.dispose()


def login(client, slug, remember=False):
    return client.post(
        "/auth/login",
        base_url=f"http://{slug}.example.test",
        data={
            "email": f"{slug}@example.test",
            "password": f"{slug}-password",
            "remember_me": "y" if remember else "",
        },
    )


def test_interleaved_reads_and_writes_are_isolated(tenant_app):
    client = tenant_app.test_client()
    for slug, host in (("alpha", ALPHA), ("beta", BETA), ("alpha", ALPHA), ("beta", BETA)):
        payload = client.get("/__tenant", base_url=f"http://{host}").get_json()
        assert payload == {"tenant": slug, "customer": f"{slug} customer", "count": 1}

    assert client.post("/__customer", base_url=f"http://{ALPHA}", data={"name": "alpha changed"}).status_code == 204
    assert client.get("/__tenant", base_url=f"http://{BETA}").get_json()["customer"] == "beta customer"
    assert client.get("/__tenant", base_url=f"http://{ALPHA}").get_json()["customer"] == "alpha changed"


def test_equal_user_ids_and_copied_session_cookies_do_not_cross_tenants(tenant_app):
    client = tenant_app.test_client()
    assert login(client, "alpha").status_code == 302
    assert client.get("/__protected", base_url=f"http://{ALPHA}").get_json()["identity"] == "alpha:1"

    cookie = client.get_cookie(tenant_app.config["SESSION_COOKIE_NAME"], domain=ALPHA)
    client.set_cookie(tenant_app.config["SESSION_COOKIE_NAME"], cookie.value, domain=BETA)
    assert client.get("/__protected", base_url=f"http://{BETA}").status_code == 302
    assert client.get("/__protected", base_url=f"http://{ALPHA}").get_json()["email"] == "alpha@example.test"

    assert login(client, "beta").status_code == 302
    for slug, host in (("beta", BETA), ("alpha", ALPHA), ("beta", BETA)):
        assert client.get("/__protected", base_url=f"http://{host}").get_json() == {
            "identity": f"{slug}:1",
            "email": f"{slug}@example.test",
        }


def test_credentials_are_looked_up_only_in_the_active_database(tenant_app):
    client = tenant_app.test_client()
    response = client.post(
        "/auth/login",
        base_url=f"http://{BETA}",
        data={"email": "alpha@example.test", "password": "alpha-password"},
    )
    assert response.status_code == 200
    assert b"Invalid email or password" in response.data
    assert client.get("/__protected", base_url=f"http://{BETA}").status_code == 302


def test_outer_app_context_does_not_reuse_request_sessions_or_users(tenant_app):
    client = tenant_app.test_client()
    with tenant_app.app_context():
        for slug in ("alpha", "beta", "alpha"):
            assert login(client, slug).status_code == 302
            response = client.get("/__protected", base_url=f"http://{slug}.example.test")
            assert response.get_json()["identity"] == f"{slug}:1"
            assert not db.session.registry.has()
            assert not hasattr(g, "tenant")


def test_remember_cookie_restores_only_its_original_tenant(tenant_app):
    client = tenant_app.test_client()
    assert login(client, "alpha", remember=True).status_code == 302
    remembered = client.get_cookie("remember_token", domain=ALPHA)
    restored = tenant_app.test_client()
    restored.set_cookie("remember_token", remembered.value, domain=BETA)
    assert restored.get("/__protected", base_url=f"http://{BETA}").status_code == 302
    restored.set_cookie("remember_token", remembered.value, domain=ALPHA)
    assert restored.get("/__protected", base_url=f"http://{ALPHA}").get_json()["identity"] == "alpha:1"


@pytest.mark.parametrize("identity", ["1", "beta:1", "alpha:not-an-id", "alpha:0", "alpha:99999999999999999999"])
def test_invalid_or_unscoped_identities_are_rejected(tenant_app, identity):
    client = tenant_app.test_client()
    with client.session_transaction(base_url=f"http://{ALPHA}") as session:
        session["_user_id"] = identity
        session["_fresh"] = True
    assert client.get("/__protected", base_url=f"http://{ALPHA}").status_code == 302


@pytest.mark.parametrize("host,status", [
    ("unknown.example.test", 404),
    ("disabled.example.test", 404),
    ("localhost", 404),
    ("alpha.example.test:invalid", 400),
])
def test_rejected_hosts_never_query_a_database_or_reach_csrf(tenant_app, monkeypatch, host, status):
    def forbidden(*args, **kwargs):
        raise AssertionError("Rejected hosts must not access a database or CSRF.")

    tenant_app.config["WTF_CSRF_ENABLED"] = True
    monkeypatch.setattr(csrf, "protect", forbidden)
    with tenant_app.app_context():
        engines = list(db.engines.values()) + list(tenant_app.extensions["tenancy"].engines.values())
    for engine in engines:
        event.listen(engine, "before_cursor_execute", forbidden)
    try:
        client = tenant_app.test_client()
        for path in ("/", "/admin/", "/does-not-exist"):
            assert client.get(path, environ_overrides={"HTTP_HOST": host}).status_code == status
        assert client.post("/auth/login", environ_overrides={"HTTP_HOST": host}).status_code == status
    finally:
        for engine in engines:
            event.remove(engine, "before_cursor_execute", forbidden)


def test_host_resolution_precedes_csrf_for_known_hosts(tenant_app, monkeypatch):
    def check_context():
        assert g.tenant.slug == "alpha"

    tenant_app.config["WTF_CSRF_ENABLED"] = True
    monkeypatch.setattr(csrf, "protect", check_context)
    response = tenant_app.test_client().post(
        "/__customer", base_url=f"http://{ALPHA}", data={"name": "resolved first"},
    )
    assert response.status_code == 204


def test_normalized_aliases_and_trusted_proxy_hosts(tenant_app):
    client = tenant_app.test_client()
    response = client.get("/__tenant", base_url="http://WWW.ALPHA.EXAMPLE.TEST.:8080")
    assert response.get_json()["tenant"] == "alpha"
    response = client.get(
        "/__tenant",
        base_url="http://proxy.internal",
        headers={"X-Forwarded-Host": BETA, "X-Forwarded-Proto": "https"},
    )
    assert response.get_json()["tenant"] == "beta"


def test_untrusted_forwarded_host_cannot_select_a_tenant(tenant_app):
    app = create_app("testing", {
        "TENANTS": tenant_app.config["TENANTS"],
        "TENANTS_JSON": "",
        "TRUST_PROXY": False,
    })
    try:
        response = app.test_client().get("/", base_url="http://unknown.example.test", headers={"X-Forwarded-Host": ALPHA})
        assert response.status_code == 404
    finally:
        with app.app_context():
            for engine in list(db.engines.values()) + list(app.extensions["tenancy"].engines.values()):
                engine.dispose()


def test_request_teardown_rolls_back_uncommitted_work(tenant_app):
    client = tenant_app.test_client()
    assert client.post("/__uncommitted", base_url=f"http://{ALPHA}").status_code == 204
    assert client.get("/__tenant", base_url=f"http://{ALPHA}").get_json()["count"] == 1
    assert client.get("/__tenant", base_url=f"http://{BETA}").get_json()["count"] == 1


def test_concurrent_requests_use_separate_tenant_sessions(tenant_app):
    hosts = [ALPHA, BETA] * 8

    def probe(host):
        with tenant_app.test_client() as client:
            return client.get("/__tenant", base_url=f"http://{host}").get_json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(probe, hosts))
    for host, result in zip(hosts, results):
        slug = host.split(".")[0]
        assert result["tenant"] == slug
        assert result["customer"] == f"{slug} customer"


def test_router_has_no_implicit_database_outside_a_tenant_context(tenant_app):
    with tenant_app.app_context():
        with pytest.raises(RuntimeError, match="active tenant"):
            db.session.execute(text("select 1"))


def test_session_cannot_change_tenant_or_use_another_explicit_bind(tenant_app):
    registry = tenant_app.extensions["tenancy"]
    with tenant_app.app_context(), tenant_context("alpha"):
        session = db.session()
        assert session.execute(text("select 1")).scalar_one() == 1
        with pytest.raises(InvalidRequestError, match="explicit bind"):
            session.get_bind(bind=registry.engines["beta"])
        g.tenant = registry.tenants["beta"]
        with pytest.raises(InvalidRequestError, match="switch tenants"):
            session.execute(text("select 1"))


def test_engine_pools_are_bounded_and_disabled_tenants_have_no_engine(tenant_app):
    registry = tenant_app.extensions["tenancy"]
    assert set(registry.engines) == {"alpha", "beta"}
    for engine in registry.engines.values():
        assert engine.pool.size() == 2
        assert engine.pool._max_overflow == 0
        assert engine.pool.checkedout() == 0


@pytest.mark.parametrize("host,expected", [
    ("WWW.Alpha.Example.Test:443", ALPHA),
    ("alpha.example.test.", ALPHA),
    ("127.0.0.1:5000", "127.0.0.1"),
    ("[::1]:5000", "::1"),
])
def test_host_normalization(host, expected):
    assert normalize_host(host) == expected


@pytest.mark.parametrize("host", ["", "alpha.example.test:bad", "alpha.example.test/path", "user@alpha.example.test", "alpha example.test", "alpha.example.test:65536"])
def test_malformed_hosts_are_rejected(host):
    with pytest.raises(ValueError):
        normalize_host(host)


def test_registry_requires_explicit_hosts_without_the_local_default():
    with pytest.raises(ValueError, match="nonempty TENANTS"):
        TenantRegistry.from_config({"TENANT_ALLOW_DEFAULT": False})


def test_registry_loads_json_control_data_without_a_database():
    registry = TenantRegistry.from_config({
        "TENANTS_JSON": '{"alpha":{"hosts":["alpha.example.test"],"database_uri":"sqlite:///:memory:"}}',
    })
    assert registry.resolve(ALPHA).slug == "alpha"
    assert registry.resolve("unknown.example.test") is None
    assert registry.default_slug is None
    assert not registry.engines


def test_default_request_context_accepts_only_registered_local_hosts(app):
    with app.test_request_context("/"):
        assert get_current_tenant().slug == "default"
        assert User.query.count() == 0
    with app.test_request_context("/", base_url="http://unknown.example.test"):
        with pytest.raises(RuntimeError, match="active tenant"):
            db.session.execute(text("select 1"))


def test_registry_rejects_ambiguous_www_aliases():
    with pytest.raises(ValueError, match="assigned more than once"):
        TenantRegistry.from_config({
            "TENANTS": {
                "alpha": {"hosts": [ALPHA], "database_uri": "sqlite:///:memory:"},
                "beta": {"hosts": [f"www.{ALPHA}"], "database_uri": "sqlite:///:memory:"},
            },
        })


TENANT_SETTINGS = {
    "alpha": {
        "BUSINESS_NAME": "Alpha Services",
        "BUSINESS_PHONE": "555-0101",
        "BUSINESS_EMAIL": "alpha-office@example.test",
        "TAGLINE": "Alpha tagline",
        "SERVICE_AREA": "Alpha area",
        "BUSINESS_ADDRESS": "1 Alpha Street",
        "COMPENSATION_CURRENCY": "cad",
        "SITE_LOGO_PATH": "/assets/alpha-logo.png",
        "SITE_LOGO_ALT": "Alpha logo",
        "SOCIAL_FACEBOOK_ENABLED": True,
        "SOCIAL_FACEBOOK_URL": "https://social.example.test/alpha",
        "CANONICAL_ORIGIN": "https://www.alpha.example.test/",
        "ADMIN_NOTIFICATION_EMAIL": "alpha-alerts@example.test",
        "DEFAULT_FROM_EMAIL": "alpha-sender@example.test",
        "EMAIL_FROM_NAME": "Alpha Dispatch",
        "EMAIL_ENABLED": True,
        "SMTP_HOST": "smtp.alpha.example.test",
        "SMTP_PORT": 2525,
        "SMTP_USERNAME": "alpha-smtp",
        "SMTP_PASSWORD": "alpha-test-password",
        "SMTP_USE_TLS": False,
        "SMTP_USE_SSL": False,
        "RECAPTCHA_ENABLED": False,
        "SITE_THEME": themes.DEFAULT_SLUG,
        "RATE_LIMIT_ENABLED": True,
        "RATE_LIMIT_FORM_REQUESTS": 1,
        "RATE_LIMIT_FORM_WINDOW_SECONDS": 600,
        "RATE_LIMIT_LOGIN_REQUESTS": 100,
        **{
            key: False for key in (
                "ENABLE_SERVICES", "ENABLE_GALLERY", "ENABLE_SCHEDULING", "ENABLE_CALENDAR",
                "ENABLE_STAFF_MANAGEMENT", "ENABLE_CUSTOMER_RECORDS", "ENABLE_RECURRING_WORK",
            )
        },
    },
    "beta": {
        "COMPANY_NAME": "Beta Works",
        "BUSINESS_PHONE": "555-0202",
        "BUSINESS_EMAIL": "beta-office@example.test",
        "SITE_LOGO": {"path": "assets/beta-logo.png", "alt": "Beta logo"},
        "SOCIAL_LINKS": {"facebook": {"enabled": True, "url": "https://social.example.test/beta"}},
        "CANONICAL_ORIGIN": "https://beta.example.test",
        "ADMIN_NOTIFICATION_EMAIL": "beta-alerts@example.test",
        "EMAIL_ENABLED": True,
        "SMTP_HOST": "smtp.beta.example.test",
        "SMTP_PORT": 2526,
        "SMTP_USERNAME": "beta-smtp",
        "SMTP_PASSWORD": "beta-test-password",
        "SMTP_USE_TLS": False,
        "SMTP_USE_SSL": False,
        "RECAPTCHA_ENABLED": True,
        "RECAPTCHA_SITE_KEY": "beta-site-key",
        "RECAPTCHA_SECRET_KEY": "beta-secret-key",
        "RECAPTCHA_MIN_SCORE": 0.7,
        "RECAPTCHA_VERIFY_URL": "https://recaptcha.beta.example.test/verify",
        "SITE_THEME": themes.DEFAULT_SLUG,
        "RATE_LIMIT_ENABLED": True,
        "RATE_LIMIT_FORM_REQUESTS": 1,
        "RATE_LIMIT_FORM_WINDOW_SECONDS": 30,
        "RATE_LIMIT_LOGIN_REQUESTS": 100,
        **{
            key: True for key in (
                "ENABLE_SERVICES", "ENABLE_GALLERY", "ENABLE_SCHEDULING", "ENABLE_CALENDAR",
                "ENABLE_STAFF_MANAGEMENT", "ENABLE_CUSTOMER_RECORDS", "ENABLE_RECURRING_WORK",
            )
        },
    },
}


@pytest.mark.parametrize("tenant_app", [TENANT_SETTINGS], indirect=True)
class TestTenantSettings:
    def test_interleaved_pages_render_tenant_branding_and_flags(self, tenant_app):
        client = tenant_app.test_client()
        for slug, name, phone in (
            ("alpha", "Alpha Services", "555-0101"),
            ("beta", "Beta Works", "555-0202"),
            ("alpha", "Alpha Services", "555-0101"),
        ):
            response = client.get("/", base_url=f"http://{slug}.example.test")
            assert response.status_code == 200
            body = response.get_data(as_text=True)
            assert name in body
            assert f"tel:{phone}" in body
            assert f"/static/assets/{slug}-logo.png" in body
            assert f"https://social.example.test/{slug}" in body
            assert ('href="/schedule-work"' in body) is (slug == "beta")
            assert ('href="/services"' in body) is (slug == "beta")
            assert ('href="/gallery"' in body) is (slug == "beta")
            assert ("Beta Works" if slug == "alpha" else "Alpha Services") not in body

    def test_public_and_admin_guards_follow_tenant_flags(self, tenant_app):
        client = tenant_app.test_client()
        for path, alpha_status in (("/schedule-work", 302), ("/services", 404), ("/gallery", 404)):
            assert client.get(path, base_url=f"http://{ALPHA}").status_code == alpha_status
            assert client.get(path, base_url=f"http://{BETA}").status_code == 200
        for slug, status in (("alpha", 302), ("beta", 200)):
            assert login(client, slug).status_code == 302
            assert client.get("/__protected", base_url=f"http://{slug}.example.test").status_code == 200
            response = client.get("/admin/calendar", base_url=f"http://{slug}.example.test")
            assert response.status_code == status
            if slug == "alpha":
                assert response.headers["Location"] == "/admin/"

    def test_import_guards_use_tenant_settings(self, tenant_app):
        from werkzeug.exceptions import NotFound
        from app.admin.routes import _ensure_import_enabled

        with tenant_app.app_context(), tenant_context("alpha"):
            for entity in ("customers", "staff"):
                with pytest.raises(NotFound):
                    _ensure_import_enabled(entity)
        with tenant_app.app_context(), tenant_context("beta"):
            for entity in ("customers", "staff"):
                assert _ensure_import_enabled(entity).key == entity

    def test_quote_service_obeys_scheduling_and_service_flags(self, tenant_app, monkeypatch):
        from app.forms.quote_request import QuoteRequestForm
        from app.services.quotes import create_quote_request

        monkeypatch.setattr("app.services.quotes._trigger_email_hooks", lambda quote_request: None)
        for slug, count in (("alpha", 0), ("beta", 1)):
            with tenant_app.test_request_context("/quote-request", base_url=f"http://{slug}.example.test"):
                assert tenant_app.preprocess_request() is None
                form = QuoteRequestForm(formdata=None, data={
                    "full_name": "Settings test",
                    "phone": "555-0100",
                    "city": "Test City",
                    "services": [f"{slug} cleaning"],
                    "preferred_date": date.today(),
                })
                quote_request = create_quote_request(form, [], request_type="Work request")
                assert Appointment.query.count() == count
                assert len(quote_request.services) == count

    def test_theme_selection_is_scoped_to_the_active_tenant(self, tenant_app, tmp_path):
        legacy = tmp_path / "instance" / "theme.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text('{"slug":"stormy-morning"}', encoding="utf-8")
        for slug in ("alpha", "beta"):
            with tenant_app.app_context(), tenant_context(slug):
                assert themes.get_active_slug(tenant_app) == themes.DEFAULT_SLUG

        client = tenant_app.test_client()
        assert login(client, "alpha").status_code == 302
        assert client.post(
            "/admin/settings/appearance", base_url=f"http://{ALPHA}",
            data={"theme_slug": "stormy-morning"},
        ).status_code == 302
        with tenant_app.app_context(), tenant_context("alpha"):
            assert themes.get_active_slug(tenant_app) == "stormy-morning"
        with tenant_app.app_context(), tenant_context("beta"):
            assert themes.get_active_slug(tenant_app) == themes.DEFAULT_SLUG
        assert (legacy.parent / "tenants" / "alpha" / "theme.json").is_file()
        assert not (legacy.parent / "tenants" / "beta" / "theme.json").exists()
        assert "--theme-brand:" in client.get("/", base_url=f"http://{ALPHA}").get_data(as_text=True)
        assert "--theme-brand:" not in client.get("/", base_url=f"http://{BETA}").get_data(as_text=True)

    def test_rate_limits_are_isolated_for_the_same_ip(self, tenant_app):
        client = tenant_app.test_client()
        first = client.post("/quote-request", base_url=f"http://{ALPHA}")
        second = client.post("/quote-request", base_url=f"http://{ALPHA}")
        other = client.post("/quote-request", base_url=f"http://{BETA}")
        assert first.status_code == other.status_code == 200
        assert second.status_code == 429
        assert second.headers["Retry-After"] == "600"
        beta_limit = client.post("/quote-request", base_url=f"http://{BETA}")
        assert beta_limit.status_code == 429
        assert beta_limit.headers["Retry-After"] == "30"

    def test_email_hooks_use_tenant_settings_outside_requests(self, tenant_app, monkeypatch):
        smtp = MagicMock()
        monkeypatch.setattr("app.services.email.smtplib.SMTP", smtp)
        for slug in ("alpha", "beta"):
            with tenant_app.app_context(), tenant_context(slug):
                quote_request = QuoteRequest(
                    full_name="Email test", city="Test City", email="customer@example.test",
                )
                db.session.add(quote_request)
                db.session.commit()
                assert email_hooks.send_admin_notification(quote_request) is True
                assert email_hooks.send_customer_confirmation(quote_request) is True
        assert [call.args[:2] for call in smtp.call_args_list] == [
            ("smtp.alpha.example.test", 2525), ("smtp.alpha.example.test", 2525),
            ("smtp.beta.example.test", 2526), ("smtp.beta.example.test", 2526),
        ]
        server = smtp.return_value.__enter__.return_value
        messages = [call.args[0] for call in server.send_message.call_args_list]
        for slug, name, origin, admin, customer in (
            ("alpha", "Alpha Services", "https://www.alpha.example.test", messages[0], messages[1]),
            ("beta", "Beta Works", "https://beta.example.test", messages[2], messages[3]),
        ):
            assert admin["To"] == f"{slug}-alerts@example.test"
            assert name in admin.get_content()
            assert f"{origin}/admin/requests/1" in admin.get_content()
            assert customer["To"] == "customer@example.test"
            assert name in customer.get_content()
            assert TENANT_SETTINGS[slug]["BUSINESS_PHONE"] in customer.get_content()
        assert messages[0]["From"] == "Alpha Dispatch <alpha-sender@example.test>"
        assert messages[2]["From"] == "Beta Works <beta-office@example.test>"
        assert [call.args for call in server.login.call_args_list] == [
            ("alpha-smtp", "alpha-test-password"), ("alpha-smtp", "alpha-test-password"),
            ("beta-smtp", "beta-test-password"), ("beta-smtp", "beta-test-password"),
        ]

    def test_email_urls_ignore_the_incoming_scheme_and_port(self, tenant_app):
        with tenant_app.test_request_context("/", base_url=f"http://{ALPHA}:8080"):
            assert tenant_app.preprocess_request() is None
            assert email_hooks._request_url(QuoteRequest(id=7)) == "https://www.alpha.example.test/admin/requests/7"

    def test_recaptcha_rendering_and_verification_use_tenant_keys(self, tenant_app, monkeypatch):
        client = tenant_app.test_client()
        assert "beta-site-key" not in client.get("/quote-request", base_url=f"http://{ALPHA}").get_data(as_text=True)
        assert "render=beta-site-key" in client.get("/quote-request", base_url=f"http://{BETA}").get_data(as_text=True)
        verifier = MagicMock()
        verifier.return_value.__enter__.return_value.read.return_value = (
            b'{"success":true,"action":"quote_request","score":0.6}'
        )
        monkeypatch.setattr(recaptcha, "urlopen", verifier)
        with tenant_app.app_context(), tenant_context("alpha"):
            assert recaptcha.verify_recaptcha_submission("", "quote_request").success is True
        verifier.assert_not_called()
        with tenant_app.app_context(), tenant_context("beta"):
            assert recaptcha.verify_recaptcha_submission("token", "quote_request").success is False
        assert verifier.call_args.args[0] == "https://recaptcha.beta.example.test/verify"
        assert parse_qs(verifier.call_args.args[1].decode()) == {
            "secret": ["beta-secret-key"], "response": ["token"],
        }

    def test_accessor_is_read_only_and_does_not_change_app_defaults(self, tenant_app):
        keys = ("BUSINESS_NAME", "BUSINESS_PHONE", "SITE_LOGO", "SOCIAL_LINKS", "ENABLE_SCHEDULING")
        before = deepcopy({key: tenant_app.config[key] for key in keys})
        with tenant_app.app_context(), tenant_context("alpha"):
            settings = current_tenant_settings()
            assert settings["COMPANY_NAME"] == "Alpha Services"
            assert tenant_config("STAFF_COMPENSATION_CURRENCY") == "CAD"
            assert tenant_config("SMTP_TIMEOUT") == tenant_app.config["SMTP_TIMEOUT"]
            assert tenant_config("MISSING_SETTING", "fallback") == "fallback"
            with pytest.raises(TypeError):
                settings["BUSINESS_NAME"] = "changed"
            with pytest.raises(TypeError):
                settings["SITE_LOGO"]["path"] = "changed"
            with pytest.raises(TypeError):
                settings["SOCIAL_LINKS"]["facebook"]["enabled"] = False
        with tenant_app.app_context(), tenant_context("beta"):
            assert tenant_config("BUSINESS_NAME") == "Beta Works"
        assert {key: tenant_app.config[key] for key in keys} == before


@pytest.mark.parametrize("settings", [
    {"ENABLE_SCHEDULING": "false"},
    {"SMTP_PORT": 0},
    {"RECAPTCHA_MIN_SCORE": 2},
    {"CANONICAL_ORIGIN": "http://alpha.example.test"},
    {"CANONICAL_ORIGIN": "https://alpha.example.test/subpath"},
    {"CANONICAL_ORIGIN": "https://user:password@alpha.example.test"},
    {"SITE_LOGO": {"path": False}},
    {"SOCIAL_LINKS": {"facebook": {"enabled": "false"}}},
    {"UPLOAD_FOLDER": "not-supported-in-wave-2"},
])
def test_invalid_tenant_setting_values_fail_at_startup(settings):
    with pytest.raises(ValueError):
        TenantRegistry.from_config({
            "TENANTS": {"alpha": {
                "hosts": [ALPHA], "database_uri": "sqlite:///:memory:", "settings": settings,
            }},
        })


def test_rate_limit_pruning_preserves_other_tenants_longer_windows(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now[0])
    store = rate_limit._FixedWindowStore()
    assert store.hit("alpha:forms:client", 600) == 1
    now[0] = 10
    for index in range(5000):
        store.hit(f"beta:forms:{index}", 1)
    assert store.hit("alpha:forms:client", 600) == 2
    now[0] = 601
    assert store.hit("alpha:forms:client", 600) == 1


def test_flat_application_logo_and_social_defaults_are_available_to_tenants(app):
    app.config.update(
        SITE_LOGO_PATH="/assets/default-logo.png",
        SITE_LOGO_ALT="Default logo",
        SOCIAL_FACEBOOK_ENABLED=True,
        SOCIAL_FACEBOOK_URL="https://social.example.test/default",
    )
    settings = current_tenant_settings()
    assert settings["SITE_LOGO"] == {"path": "assets/default-logo.png", "alt": "Default logo"}
    assert settings["SOCIAL_LINKS"]["facebook"]["url"] == "https://social.example.test/default"
    assert tenant_config("SOCIAL_FACEBOOK_ENABLED") is True
    assert tenant_config("SOCIAL_FACEBOOK_URL") == "https://social.example.test/default"


MEDIA_SETTINGS = {
    slug: {"ENABLE_GALLERY": True, "ENABLE_CUSTOMER_RECORDS": True}
    for slug in ("alpha", "beta")
}


def png_bytes(color):
    output = BytesIO()
    Image.new("RGB", (2, 2), color).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture()
def tenant_media_files(tenant_app, monkeypatch):
    monkeypatch.setattr(uploads, "uuid4", lambda: SimpleNamespace(hex="same"))
    client = tenant_app.test_client()
    files = {}
    for slug, color in (("alpha", "red"), ("beta", "blue")):
        content = png_bytes(color)
        base_url = f"http://{slug}.example.test"
        response = client.post("/quote-request", base_url=base_url, data={
            "full_name": f"{slug} requester", "phone": "555-0100", "city": "Test City",
            "photos": (BytesIO(content), "photo.png"),
        }, content_type="multipart/form-data")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/thank-you")
        assert login(client, slug).status_code == 302
        response = client.post("/admin/customers/1/photos", base_url=base_url, data={
            "customer-photos-photos": (BytesIO(content), "photo.png"),
        }, content_type="multipart/form-data")
        assert response.status_code == 302
        with tenant_app.app_context(), tenant_context(slug):
            GalleryItem.query.delete()
            db.session.commit()
        response = client.post("/admin/content/gallery", base_url=base_url, data={
            "gallery-create-image": (BytesIO(content), "photo.png"),
            "gallery-create-title": f"{slug} photo",
            "gallery-create-service_id": "0",
            "gallery-create-submit": "Upload Image",
        }, content_type="multipart/form-data")
        assert response.status_code == 302
        with tenant_app.app_context(), tenant_context(slug):
            assert QuoteRequest.query.one().id == Customer.query.one().id == GalleryItem.query.one().id == 1
            files[slug] = {
                "root": tenant_upload_root(), "content": content,
                "request": RequestPhoto.query.one().file_path,
                "customer": CustomerPhoto.query.one().file_path,
                "gallery": GalleryItem.query.one().image_path,
            }
    return files


@pytest.mark.parametrize("tenant_app", [MEDIA_SETTINGS], indirect=True)
class TestTenantMedia:
    def test_route_uploads_with_equal_ids_write_separate_tenant_directories(self, tenant_app, tenant_media_files):
        for slug in ("alpha", "beta"):
            data = tenant_media_files[slug]
            assert data["root"] == Path(tenant_app.instance_path).resolve() / "tenants" / slug / "uploads"
            for category in ("request", "customer", "gallery"):
                key = data[category]
                assert not Path(key).is_absolute()
                assert "\\" not in key and key.startswith("uploads/")
                assert slug not in key
                assert (data["root"] / media.storage_key(key)).read_bytes() == data["content"]
        assert tenant_media_files["alpha"]["root"] != tenant_media_files["beta"]["root"]
        for category in ("request", "customer", "gallery"):
            assert tenant_media_files["alpha"][category] == tenant_media_files["beta"][category]
        assert not Path(tenant_app.config["UPLOAD_FOLDER"]).exists()

    def test_private_media_serves_only_the_authenticated_tenants_bytes(self, tenant_app, tenant_media_files):
        client = tenant_app.test_client()
        for slug in ("alpha", "beta", "alpha"):
            assert login(client, slug).status_code == 302
            for category in ("request", "customer"):
                key = media.storage_key(tenant_media_files[slug][category])
                response = client.get(f"/admin/media/{key}", base_url=f"http://{slug}.example.test")
                assert response.status_code == 200
                assert response.data == tenant_media_files[slug]["content"]
                assert "private" in response.headers["Cache-Control"]
        anonymous = tenant_app.test_client()
        assert anonymous.get("/admin/media/quote_requests/1/same-photo.png", base_url=f"http://{ALPHA}").status_code in (302, 401, 404)

    def test_private_file_uploaded_only_to_beta_is_not_available_on_alpha(self, tenant_app, tenant_media_files):
        with tenant_app.app_context(), tenant_context("beta"):
            uploaded = uploads.save_customer_photos([
                FileStorage(BytesIO(png_bytes("blue")), filename="beta-only.png", content_type="image/png"),
            ], 1)
            key = media.storage_key(uploaded[0].file_path)
        client = tenant_app.test_client()
        assert login(client, "alpha").status_code == 302
        assert client.get(f"/admin/media/{key}", base_url=f"http://{ALPHA}").status_code == 404
        assert login(client, "beta").status_code == 302
        assert client.get(f"/admin/media/{key}", base_url=f"http://{BETA}").data == png_bytes("blue")

    def test_public_gallery_urls_and_previews_use_tenant_media(self, tenant_app, tenant_media_files):
        client = tenant_app.test_client()
        for slug in ("alpha", "beta"):
            key = tenant_media_files[slug]["gallery"]
            with tenant_app.test_request_context("/", base_url=f"http://{slug}.example.test"):
                assert tenant_app.preprocess_request() is None
                url = media.media_url(key)
            assert url == "/media/gallery/same-photo.png"
            response = client.get(url, base_url=f"http://{slug}.example.test")
            assert response.status_code == 200
            assert response.data == tenant_media_files[slug]["content"]
            assert f'src="{url}"' in client.get("/gallery", base_url=f"http://{slug}.example.test").get_data(as_text=True)
            assert login(client, slug).status_code == 302
            assert f'src="{url}"' in client.get("/admin/content/gallery", base_url=f"http://{slug}.example.test").get_data(as_text=True)
        assert client.get("/media/customers/1/same-photo.png", base_url=f"http://{ALPHA}").status_code == 404

    def test_directory_cleanup_cannot_delete_the_other_tenants_photos(self, tenant_app, tenant_media_files):
        with tenant_app.app_context(), tenant_context("alpha"):
            uploads.cleanup_request_photo_dir(1)
            uploads.cleanup_customer_photo_dir(1)
        alpha = tenant_media_files["alpha"]
        beta = tenant_media_files["beta"]
        for category in ("request", "customer"):
            assert not (alpha["root"] / media.storage_key(alpha[category])).exists()
            assert (beta["root"] / media.storage_key(beta[category])).read_bytes() == beta["content"]

    def test_gallery_deletion_uses_the_tenant_root_and_rejects_escape_keys(self, tenant_app, tenant_media_files):
        alpha = tenant_media_files["alpha"]
        beta = tenant_media_files["beta"]
        with tenant_app.app_context(), tenant_context("alpha"):
            uploads.delete_gallery_image("../../beta/uploads/gallery/same-photo.png")
            uploads.delete_gallery_image(str(beta["root"] / media.storage_key(beta["gallery"])))
            uploads.delete_gallery_image(alpha["customer"])
            assert (alpha["root"] / media.storage_key(alpha["customer"])).exists()
            uploads.delete_gallery_image(alpha["gallery"])
        assert not (alpha["root"] / media.storage_key(alpha["gallery"])).exists()
        assert (beta["root"] / media.storage_key(beta["gallery"])).read_bytes() == beta["content"]

    def test_partial_customer_batch_cleanup_preserves_existing_and_other_tenant_files(self, tenant_app, tenant_media_files):
        with tenant_app.app_context(), tenant_context("alpha"):
            with pytest.raises(BadRequest):
                uploads.save_customer_photos([
                    FileStorage(BytesIO(png_bytes("red")), filename="partial.png", content_type="image/png"),
                    FileStorage(BytesIO(b"not an image"), filename="bad.png", content_type="image/png"),
                ], 1)
        for slug in ("alpha", "beta"):
            data = tenant_media_files[slug]
            assert (data["root"] / media.storage_key(data["customer"])).read_bytes() == data["content"]
            assert not (data["root"] / "customers" / "1" / "same-partial.png").exists()

    def test_customer_commit_failure_removes_only_the_new_tenant_upload(self, tenant_app, tenant_media_files, monkeypatch):
        from app.services.admin_requests import upload_customer_photos

        with tenant_app.app_context(), tenant_context("alpha"):
            session = db.session()
            def fail_commit():
                raise RuntimeError("simulated commit failure")
            monkeypatch.setattr(session, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="simulated commit failure"):
                upload_customer_photos(1, [
                    FileStorage(BytesIO(png_bytes("red")), filename="failed.png", content_type="image/png"),
                ])
            assert CustomerPhoto.query.count() == 1
        for slug in ("alpha", "beta"):
            data = tenant_media_files[slug]
            assert (data["root"] / media.storage_key(data["customer"])).read_bytes() == data["content"]
            assert not (data["root"] / "customers" / "1" / "same-failed.png").exists()

    def test_gallery_failure_rolls_back_and_preserves_other_tenant_files(self, tenant_app, tenant_media_files):
        from app.services.gallery_catalog import create_gallery_item

        with tenant_app.app_context(), tenant_context("alpha"):
            with pytest.raises(BadRequest):
                create_gallery_item(
                    image_file=FileStorage(BytesIO(png_bytes("red")), filename="failed.png", content_type="image/png"),
                    title="",
                )
            assert GalleryItem.query.count() == 1
        for slug in ("alpha", "beta"):
            data = tenant_media_files[slug]
            assert (data["root"] / media.storage_key(data["gallery"])).read_bytes() == data["content"]
            assert not (data["root"] / "gallery" / "same-failed.png").exists()

    def test_shared_static_uploads_are_blocked_even_if_the_file_exists(self, tenant_app, tmp_path, monkeypatch):
        static_root = tmp_path / "shared-static"
        gallery = static_root / "uploads" / "gallery"
        gallery.mkdir(parents=True)
        (gallery / "shared.png").write_bytes(png_bytes("blue"))
        monkeypatch.setattr(tenant_app, "static_folder", str(static_root))
        client = tenant_app.test_client()
        for path in (
            "/static/uploads/gallery/shared.png",
            "/static/./uploads/gallery/shared.png",
            "/static/uploads//gallery/shared.png",
            "/static/uploads%5cgallery%5cshared.png",
            "/static/uploads./gallery/shared.png",
            "/static/uploads%20/gallery/shared.png",
        ):
            assert client.get(path, base_url=f"http://{ALPHA}").status_code == 404
            assert client.get(path, base_url=f"http://{BETA}").status_code == 404

    def test_resolved_gallery_links_cannot_expose_private_or_other_tenant_files(self, tenant_app, tenant_media_files, monkeypatch):
        alpha = tenant_media_files["alpha"]
        beta = tenant_media_files["beta"]
        original_resolve = Path.resolve
        redirects = {
            alpha["root"] / "gallery" / "private.png": alpha["root"] / media.storage_key(alpha["request"]),
            alpha["root"] / "gallery" / "other-tenant.png": beta["root"] / media.storage_key(beta["gallery"]),
        }
        def redirected(path, *args, **kwargs):
            return redirects.get(path, original_resolve(path, *args, **kwargs))
        monkeypatch.setattr(Path, "resolve", redirected)
        client = tenant_app.test_client()
        assert client.get("/media/gallery/private.png", base_url=f"http://{ALPHA}").status_code == 404
        assert client.get("/media/gallery/other-tenant.png", base_url=f"http://{ALPHA}").status_code == 404

    def test_partial_file_save_failure_removes_only_the_new_upload(self, tenant_app, tenant_media_files, monkeypatch):
        file = FileStorage(BytesIO(png_bytes("red")), filename="failed.png", content_type="image/png")
        def fail_save(target):
            Path(target).write_bytes(b"partial file")
            raise OSError("simulated file save failure")
        monkeypatch.setattr(file, "save", fail_save)
        with tenant_app.app_context(), tenant_context("alpha"):
            with pytest.raises(OSError, match="simulated file save failure"):
                uploads.save_customer_photos([file], 1)
        for slug in ("alpha", "beta"):
            data = tenant_media_files[slug]
            assert (data["root"] / media.storage_key(data["customer"])).read_bytes() == data["content"]
            assert not (data["root"] / "customers" / "1" / "same-failed.png").exists()

    @pytest.mark.parametrize("key", [
        "../beta/uploads/gallery/photo.png", "/gallery/photo.png",
        r"C:\uploads\gallery\photo.png", "gallery/photo.png:alternate",
        "gallery/../customers/1/photo.png", "gallery//photo.png", "gallery/\x00photo.png",
    ])
    def test_media_resolver_rejects_malformed_storage_keys(self, tenant_app, key):
        with tenant_app.app_context(), tenant_context("alpha"):
            assert media.resolve_public_file(key) is None
            assert media.resolve_private_file(key) is None


@pytest.mark.parametrize("tenant_app", [MEDIA_SETTINGS], indirect=True)
def test_quote_upload_failure_rolls_back_only_alpha_storage(tenant_app, monkeypatch):
    monkeypatch.setattr(uploads, "uuid4", lambda: SimpleNamespace(hex="same"))
    client = tenant_app.test_client()
    data = {"full_name": "Beta requester", "phone": "555-0100", "city": "Test City"}
    response = client.post("/quote-request", base_url=f"http://{BETA}", data={
        **data, "photos": (BytesIO(png_bytes("blue")), "photo.png"),
    }, content_type="multipart/form-data")
    assert response.status_code == 302
    response = client.post("/quote-request", base_url=f"http://{ALPHA}", data={
        **data, "photos": [
            (BytesIO(png_bytes("red")), "photo.png"),
            (BytesIO(b"not an image"), "bad.png"),
        ],
    }, content_type="multipart/form-data")
    assert response.status_code == 200
    with tenant_app.app_context(), tenant_context("alpha"):
        assert QuoteRequest.query.count() == 0
        assert not (tenant_upload_root() / "quote_requests" / "1").exists()
    with tenant_app.app_context(), tenant_context("beta"):
        assert QuoteRequest.query.one().id == 1
        assert (tenant_upload_root() / "quote_requests" / "1" / "same-photo.png").read_bytes() == png_bytes("blue")


@pytest.mark.parametrize("tenant_app", [{
    "alpha": {"ENABLE_GALLERY": False}, "beta": {"ENABLE_GALLERY": True},
}], indirect=True)
def test_public_gallery_media_enforces_each_tenants_feature_flag(tenant_app):
    urls = {}
    for slug in ("alpha", "beta"):
        with tenant_app.app_context(), tenant_context(slug):
            key = uploads.save_gallery_image(FileStorage(
                BytesIO(png_bytes("red")), filename="gallery.png", content_type="image/png",
            ))
            GalleryItem.query.one().image_path = key
            db.session.commit()
        with tenant_app.test_request_context("/", base_url=f"http://{slug}.example.test"):
            assert tenant_app.preprocess_request() is None
            urls[slug] = media.media_url(key)
    client = tenant_app.test_client()
    assert client.get(urls["alpha"], base_url=f"http://{ALPHA}").status_code == 404
    assert client.get(urls["beta"], base_url=f"http://{BETA}").status_code == 200

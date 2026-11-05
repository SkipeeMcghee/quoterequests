from concurrent.futures import ThreadPoolExecutor

import pytest
from flask import g, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import event, text
from sqlalchemy.exc import InvalidRequestError

from app import create_app
from app.extensions import csrf, db
from app.models import Customer, User
from app.tenancy import TenantRegistry, get_current_tenant, normalize_host, tenant_context


ALPHA = "alpha.example.test"
BETA = "beta.example.test"


@pytest.fixture()
def tenant_app(tmp_path):
    app = create_app("testing", {
        "SECRET_KEY": "tenant-routing-test-key",
        "SQLALCHEMY_DATABASE_URI": "sqlite+pysqlite:///:memory:",
        "TENANTS_JSON": "",
        "TENANTS": {
            slug: {
                "hosts": [host],
                "database_uri": f"sqlite+pysqlite:///{tmp_path / (slug + '.db')}",
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
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
    })
    registry = app.extensions["tenancy"]
    for slug in ("alpha", "beta"):
        with app.app_context(), tenant_context(slug) as tenant:
            db.metadata.create_all(bind=registry.engine_for(tenant))
            user = User(email=f"{slug}@example.test")
            user.set_password(f"{slug}-password")
            customer = Customer(primary_name=f"{slug} customer", primary_city="Test City")
            db.session.add_all([user, customer])
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
        customer.primary_name = request.form["name"]
        db.session.commit()
        return "", 204

    @app.post("/__uncommitted")
    def uncommitted_customer():
        db.session.add(Customer(primary_name="discard me", primary_city="Test City"))
        db.session.flush()
        return "", 204

    try:
        yield app
    finally:
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

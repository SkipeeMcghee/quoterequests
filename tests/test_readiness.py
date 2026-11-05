import json
import logging
from contextlib import contextmanager
from urllib.error import URLError

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app import create_app
from app import monitoring
from app.extensions import db
from app.models import Appointment, Customer, GalleryItem, QuoteRequest, User
from app.tenancy import tenant_operation


def test_platform_health_does_not_query_database(app):
    statements = []
    engine = app.extensions["tenancy"].engines["default"]
    def record(*args):
        statements.append(args[2])
    event.listen(engine, "before_cursor_execute", record)
    try:
        for host in ("http://localhost", "http://unknown.example.test"):
            response = app.test_client().get("/healthz", base_url=host)
            assert response.status_code == 200 and response.json == {"status": "ok"}
            assert response.headers["X-Request-ID"]
        assert statements == []
        assert app.test_client().get("/healthz?db=1", base_url="http://unknown.example.test").status_code == 404
        assert app.test_client().get("/healthz?db=1").json == {"status": "ok"}
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_health_database_failure_is_json_503_and_never_loads_error_template(app, monkeypatch):
    def fail(*args, **kwargs):
        raise OperationalError("select 1", {}, Exception("database unavailable"))
    monkeypatch.setattr(db.session, "execute", fail)
    response = app.test_client().get("/healthz?db=1")
    assert response.status_code == 503 and response.json == {"status": "unavailable"}


def test_health_is_exempt_even_with_tenant_rate_limit_exhausted(app):
    app.config.update(RATE_LIMIT_ENABLED=True, RATE_LIMIT_FORM_REQUESTS=1)
    client = app.test_client()
    client.post("/quote-request", data={})
    assert client.post("/quote-request", data={}).status_code == 429
    for _ in range(4):
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz?db=1").status_code == 200
    from app.services.rate_limit import reset_all
    reset_all()


def test_error_reporting_is_optional_private_and_delivery_is_explicit(app, monkeypatch):
    calls = []
    @contextmanager
    def deliver(notification, timeout):
        calls.append((json.loads(notification.data), timeout))
        yield type("Response", (), {"status": 204})()
    monkeypatch.setattr(monitoring, "urlopen", deliver)
    with app.app_context():
        assert monitoring.report_exception(RuntimeError("private customer content")) is False
        app.config["ERROR_WEBHOOK_URL"] = "https://errors.example.test/hook"
        assert monitoring.report_exception(RuntimeError("private customer content")) is True
    assert calls[0][0]["exception_type"] == "RuntimeError"
    assert "private customer" not in json.dumps(calls)
    assert app.test_cli_runner().invoke(args=["test-error-reporting"]).exit_code == 0
    def fail(*args, **kwargs):
        raise URLError("offline")
    monkeypatch.setattr(monitoring, "urlopen", fail)
    assert app.test_cli_runner().invoke(args=["test-error-reporting"]).exit_code != 0


def test_unhandled_exception_reaches_reporting_hook(app, monkeypatch):
    errors = []
    monkeypatch.setattr(monitoring, "report_exception", lambda error: errors.append(type(error).__name__))
    @app.get("/synthetic-error")
    def explode():
        raise RuntimeError("synthetic")
    with pytest.raises(RuntimeError):
        app.test_client().get("/synthetic-error")
    assert errors == ["RuntimeError"]


@pytest.mark.parametrize("url", ["http://errors.test/hook", "https://user:password@errors.test", "not-a-url"])
def test_invalid_reporting_config_fails_startup(url):
    with pytest.raises(ValueError, match="HTTPS"):
        create_app("testing", {"ERROR_WEBHOOK_URL": url})


def test_structured_logs_are_json_and_do_not_include_exception_values():
    record = logging.LogRecord("app", logging.ERROR, "", 1, "Request failed", (), (RuntimeError, RuntimeError("secret"), None))
    payload = json.loads(monitoring.JsonFormatter().format(record))
    assert payload["level"] == "ERROR" and payload["exception_type"] == "RuntimeError"
    assert "secret" not in json.dumps(payload)


def test_production_logging_has_request_id_and_json_output(tmp_path):
    app = create_app("testing", {"TESTING": False, "UPLOAD_FOLDER": str(tmp_path / "uploads")})
    try:
        response = app.test_client().get("/healthz", base_url="http://monitor.example.test")
        assert response.status_code == 200
        assert len(response.headers["X-Request-ID"]) == 32
        assert all(isinstance(handler.formatter, monitoring.JsonFormatter) for handler in app.logger.handlers)
    finally:
        for handler in app.logger.handlers:
            handler.setFormatter(logging.Formatter())
        for engine in app.extensions["tenancy"].engines.values():
            engine.dispose()


@pytest.fixture
def readiness_tenants(tmp_path):
    app = create_app("testing", {
        "ERROR_WEBHOOK_URL": "",
        "TENANTS": {slug: {"hosts": [f"{slug}.example.test"],
            "database_uri": f"sqlite:///{tmp_path / (slug + '.db')}",
            "settings": {"BUSINESS_NAME": f"{slug.title()} Services", "BUSINESS_EMAIL": f"{slug}@example.test",
                "BUSINESS_PHONE": f"555-{index}", "BUSINESS_ADDRESS": f"{index} Sample Street" if slug == "alpha" else "",
                "SERVICE_AREA": f"{slug.title()} County", "DEMO_TENANT": slug == "alpha"}}
            for index, slug in enumerate(("alpha", "beta"), 1)},
    })
    app.instance_path = str(tmp_path / "instance")
    for slug in ("alpha", "beta"):
        with app.app_context(), tenant_operation(slug):
            db.metadata.create_all(bind=app.extensions["tenancy"].engines[slug])
            user = User(email=f"admin@{slug}.test")
            user.set_password("example-password")
            db.session.add(user)
            db.session.commit()
    yield app
    for engine in app.extensions["tenancy"].engines.values():
        engine.dispose()


def test_legal_pages_interpolate_only_active_tenant(readiness_tenants):
    for slug in ("alpha", "beta"):
        for path in ("/privacy-policy", "/terms"):
            response = readiness_tenants.test_client().get(path, base_url=f"http://{slug}.example.test")
            assert response.status_code == 200
            body = response.get_data(as_text=True)
            assert f"{slug.title()} Services" in body
            assert f"{slug}@example.test" in body
            assert f"{slug.title()} County" in body
            assert f"555-{1 if slug == 'alpha' else 2}" in body
            if slug == "alpha":
                assert "1 Sample Street" in body and "Beta Services" not in body
            else:
                assert "mailing address" in body and "Alpha Services" not in body


def test_demo_seed_is_idempotent_and_reset_preserves_other_tenant_and_admins(readiness_tenants):
    app = readiness_tenants
    runner = app.test_cli_runner()
    for slug in ("alpha", "beta"):
        result = runner.invoke(args=["seed-demo", "--tenant", slug])
        assert result.exit_code == 0, result.output + repr(result.exception)
        result = runner.invoke(args=["seed-demo", "--tenant", slug])
        assert result.exit_code == 0 and "already seeded" in result.output
    with app.app_context(), tenant_operation("beta"):
        beta_ids = [row.id for row in QuoteRequest.query.all()]
        assert Customer.query.count() == 2 and Appointment.query.count() == 2
    result = runner.invoke(args=["seed-demo", "--tenant", "beta", "--reset"])
    assert result.exit_code != 0 and "DEMO_TENANT" in result.output
    result = runner.invoke(args=["seed-demo", "--tenant", "beta", "--reset", "--force", "--confirm", "alpha"])
    assert result.exit_code != 0
    result = runner.invoke(args=["seed-demo", "--tenant", "alpha", "--reset"])
    assert result.exit_code == 0, result.output + repr(result.exception)
    for slug in ("alpha", "beta"):
        with app.app_context(), tenant_operation(slug):
            assert User.query.count() == 1 and QuoteRequest.query.count() == 7 and GalleryItem.query.count() == 1
            if slug == "beta":
                assert [row.id for row in QuoteRequest.query.all()] == beta_ids
    assert runner.invoke(args=["seed-demo", "--tenant", "unknown", "--reset"]).exit_code != 0


def test_demo_seed_refuses_existing_business_data_without_reset(readiness_tenants):
    with readiness_tenants.app_context(), tenant_operation("alpha"):
        db.session.add(Customer(primary_name="Existing real customer"))
        db.session.commit()
    result = readiness_tenants.test_cli_runner().invoke(args=["seed-demo", "--tenant", "alpha"])
    assert result.exit_code != 0 and "business records" in result.output


def test_force_reset_requires_exact_confirmation_and_cleans_only_target_media(readiness_tenants):
    from app.models import CustomerPhoto
    from app.tenancy import tenant_upload_root
    app = readiness_tenants
    runner = app.test_cli_runner()
    for slug in ("alpha", "beta"):
        runner.invoke(args=["seed-demo", "--tenant", slug])
        with app.app_context(), tenant_operation(slug):
            root = tenant_upload_root() / "customers" / "1"
            root.mkdir(parents=True)
            (root / "same.png").write_bytes(slug.encode())
            customer = Customer.query.first()
            db.session.add(CustomerPhoto(customer_id=customer.id, file_path="uploads/customers/1/same.png"))
            db.session.commit()
    result = runner.invoke(args=["seed-demo", "--tenant", "beta", "--reset", "--force", "--confirm", "beta"])
    assert result.exit_code == 0, repr(result.exception)
    for slug in ("alpha", "beta"):
        with app.app_context(), tenant_operation(slug):
            path = tenant_upload_root() / "customers" / "1" / "same.png"
            assert path.exists() == (slug == "alpha")
            assert User.query.count() == 1
    assert runner.invoke(args=["seed-demo", "--tenant", "alpha", "--force"]).exit_code != 0


def test_failed_demo_reset_rolls_back_and_keeps_uploads(readiness_tenants, monkeypatch):
    from app.tenancy import tenant_upload_root
    app = readiness_tenants
    assert app.test_cli_runner().invoke(args=["seed-demo", "--tenant", "alpha"]).exit_code == 0
    with app.app_context(), tenant_operation("alpha"):
        root = tenant_upload_root()
        root.mkdir(parents=True)
        sentinel = root / "sentinel.txt"
        sentinel.write_text("preserve", encoding="utf-8")
    def fail():
        raise RuntimeError("simulated commit failure")
    monkeypatch.setattr(db.session, "commit", fail)
    result = app.test_cli_runner().invoke(args=["seed-demo", "--tenant", "alpha", "--reset"])
    assert result.exit_code != 0
    with app.app_context(), tenant_operation("alpha"):
        assert Customer.query.count() == 2 and QuoteRequest.query.count() == 7
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_documented_cli_provision_admin_and_demo_flow_uses_real_migrations(tmp_path):
    app = create_app("testing", {"TENANT_REGISTRY_FILE": str(tmp_path / "tenants.json")})
    app.instance_path = str(tmp_path / "instance")
    runner = app.test_cli_runner()
    try:
        for arguments in (
            ["tenant", "create", "demo", "--domain", "localhost", "--demo"],
            ["create-admin", "--tenant", "demo", "--email", "owner@example.test", "--password", "example-password"],
            ["seed-demo", "--tenant", "demo"],
            ["seed-demo", "--tenant", "demo", "--reset"],
        ):
            result = runner.invoke(args=arguments)
            assert result.exit_code == 0, result.output + repr(result.exception)
        client = app.test_client()
        with app.app_context(), tenant_operation("demo"):
            from app.tenancy import tenant_config
            assert tenant_config("DEMO_TENANT") is True
            assert tenant_config("EMAIL_ENABLED") is False
        assert client.get("/static/assets/images/Logowhite.png").status_code == 200
        assert client.post("/auth/login", data={"email": "owner@example.test", "password": "example-password"}).status_code == 302
        with client.session_transaction() as session:
            assert session["_user_id"].startswith("demo:")
    finally:
        with app.app_context():
            for engine in set(db.engines.values()) | set(app.extensions["tenancy"].engines.values()):
                engine.dispose()

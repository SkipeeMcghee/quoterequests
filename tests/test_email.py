from __future__ import annotations

import smtplib
from email.message import EmailMessage

import pytest

from app.extensions import db
from app.models import QuoteRequest, ServiceOption
from app.services.email import build_message, load_settings, send_email
from app.services import email_hooks

SMTP_KEYS = (
    "EMAIL_ENABLED",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_USE_TLS",
    "SMTP_USE_SSL",
    "SMTP_TIMEOUT",
    "EMAIL_FROM_NAME",
    "EMAIL_REPLY_TO",
    "DEFAULT_FROM_EMAIL",
    "ADMIN_NOTIFICATION_EMAIL",
)


class RecordingSMTP:
    """Stands in for smtplib.SMTP / SMTP_SSL and records what would be sent."""

    instances: list["RecordingSMTP"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in = None
        self.messages: list[EmailMessage] = []
        RecordingSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, username, password):
        self.logged_in = (username, password)

    def send_message(self, message):
        self.messages.append(message)


class ExplodingSMTP(RecordingSMTP):
    def send_message(self, message):
        raise smtplib.SMTPServerDisconnected("relay went away")


@pytest.fixture()
def smtp_config(app):
    app.config.update(
        EMAIL_ENABLED=True,
        SMTP_HOST="smtp-relay.brevo.com",
        SMTP_PORT=587,
        SMTP_USERNAME="relay-user",
        SMTP_PASSWORD="relay-key",
        SMTP_USE_TLS=True,
        SMTP_USE_SSL=False,
        SMTP_TIMEOUT=5,
        DEFAULT_FROM_EMAIL="quotes@example.test",
        EMAIL_FROM_NAME="Example Services",
        EMAIL_REPLY_TO="",
        ADMIN_NOTIFICATION_EMAIL="owner@example.test",
    )
    return app


@pytest.fixture(autouse=True)
def _reset_recorder():
    RecordingSMTP.instances.clear()


def test_email_is_off_by_default(app):
    settings = load_settings(app.config)

    assert settings.enabled is False
    assert settings.is_deliverable is False


def test_disabled_email_never_touches_the_network(app, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("no SMTP connection should be attempted")

    monkeypatch.setattr(smtplib, "SMTP", explode)
    monkeypatch.setattr(smtplib, "SMTP_SSL", explode)

    assert send_email(to="someone@example.test", subject="hi", body="body") is False


def test_enabled_email_sends_over_starttls(smtp_config, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", RecordingSMTP)

    sent = send_email(
        to="customer@example.test", subject="Your request", body="Thanks!"
    )

    assert sent is True
    server = RecordingSMTP.instances[0]
    assert server.host == "smtp-relay.brevo.com"
    assert server.port == 587
    assert server.started_tls is True
    assert server.logged_in == ("relay-user", "relay-key")

    message = server.messages[0]
    assert message["To"] == "customer@example.test"
    assert message["Subject"] == "Your request"
    assert message["From"] == "Example Services <quotes@example.test>"
    assert "Thanks!" in message.get_content()


def test_implicit_tls_uses_smtp_ssl(smtp_config, monkeypatch):
    smtp_config.config.update(SMTP_USE_SSL=True, SMTP_USE_TLS=False, SMTP_PORT=465)
    monkeypatch.setattr(smtplib, "SMTP", RecordingSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", RecordingSMTP)

    assert send_email(to="customer@example.test", subject="s", body="b") is True
    assert RecordingSMTP.instances[0].port == 465
    assert RecordingSMTP.instances[0].started_tls is False


def test_send_failure_is_logged_not_raised(smtp_config, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", ExplodingSMTP)

    assert send_email(to="customer@example.test", subject="s", body="b") is False


def test_missing_host_is_treated_as_not_configured(smtp_config, monkeypatch):
    smtp_config.config.update(SMTP_HOST="")
    monkeypatch.setattr(smtplib, "SMTP", RecordingSMTP)

    assert send_email(to="customer@example.test", subject="s", body="b") is False
    assert RecordingSMTP.instances == []


def test_customer_confirmation_is_skipped_without_an_email(smtp_config, app, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", RecordingSMTP)

    with app.app_context():
        quote_request = QuoteRequest(
            request_number=0, full_name="Phone Only", city="Daytona Beach", phone="555-0100"
        )
        db.session.add(quote_request)
        db.session.commit()

        assert email_hooks.send_customer_confirmation(quote_request) is False

    assert RecordingSMTP.instances == []


def test_customer_confirmation_renders_the_request_details(smtp_config, app, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", RecordingSMTP)

    with app.app_context():
        service = ServiceOption.query.filter_by(name="Window Cleaning").first()
        quote_request = QuoteRequest(
            request_number=0,
            full_name="Taylor Grant",
            email="taylor@example.test",
            city="Port Orange",
            additional_notes="Second story windows.",
        )
        quote_request.services.append(service)
        db.session.add(quote_request)
        db.session.commit()

        assert email_hooks.send_customer_confirmation(quote_request) is True
        number = quote_request.request_number

    message = RecordingSMTP.instances[0].messages[0]
    body = message.get_content()
    assert message["To"] == "taylor@example.test"
    assert str(number) in message["Subject"]
    assert "Taylor Grant" in body
    assert "Window Cleaning" in body
    assert "Port Orange" in body


def test_admin_notification_goes_to_the_configured_address(smtp_config, app, client, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", RecordingSMTP)

    with app.app_context():
        quote_request = QuoteRequest(
            request_number=0, full_name="Taylor Grant", city="Port Orange", email="t@example.test"
        )
        db.session.add(quote_request)
        db.session.commit()
        request_id = quote_request.id

        with client.application.test_request_context("/quote-request"):
            assert email_hooks.send_admin_notification(quote_request) is True

    message = RecordingSMTP.instances[0].messages[0]
    assert message["To"] == "owner@example.test"
    assert "Taylor Grant" in message.get_content()
    assert f"/admin/requests/{request_id}" in message.get_content()


def test_admin_notification_skips_when_no_admin_address(smtp_config, app, monkeypatch):
    smtp_config.config.update(ADMIN_NOTIFICATION_EMAIL="")
    monkeypatch.setattr(smtplib, "SMTP", RecordingSMTP)

    with app.app_context():
        quote_request = QuoteRequest(request_number=0, full_name="X", city="Y")
        db.session.add(quote_request)
        db.session.commit()

        assert email_hooks.send_admin_notification(quote_request) is False

    assert RecordingSMTP.instances == []


def test_body_is_plain_text_with_a_message_id(smtp_config, app):
    with app.app_context():
        settings = load_settings()
        message = build_message(settings, to="a@example.test", subject="Subject", body="Line one\nLine two")

    assert message.get_content_type() == "text/plain"
    assert message["Message-ID"].endswith(">")
    assert "Line two" in message.get_content()

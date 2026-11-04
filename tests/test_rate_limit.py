"""Rate limiting behaviour for the anonymous POST endpoints."""

from __future__ import annotations

import pytest

from app.services import rate_limit


@pytest.fixture(autouse=True)
def _clean_store():
    rate_limit.reset_all()
    yield
    rate_limit.reset_all()


QUOTE_FORM = {
    "full_name": "Limit Tester",
    "phone": "555-0100",
    "city": "Daytona Beach",
    "services": ["Window Cleaning"],
}


def test_public_form_is_throttled_after_the_configured_number(app, client):
    app.config.update(RATE_LIMIT_ENABLED=True, RATE_LIMIT_FORM_REQUESTS=2, RATE_LIMIT_FORM_WINDOW_SECONDS=600)

    first = client.post("/quote-request", data=QUOTE_FORM)
    second = client.post("/quote-request", data=QUOTE_FORM)
    third = client.post("/quote-request", data=QUOTE_FORM)

    assert first.status_code != 429
    assert second.status_code != 429
    assert third.status_code == 429
    assert third.headers["Retry-After"] == "600"
    assert "slow down" in third.get_data(as_text=True).lower()


def test_limits_are_per_client_address(app, client):
    app.config.update(RATE_LIMIT_ENABLED=True, RATE_LIMIT_FORM_REQUESTS=1, RATE_LIMIT_FORM_WINDOW_SECONDS=600)

    blocked = client.post("/quote-request", data=QUOTE_FORM, environ_base={"REMOTE_ADDR": "10.0.0.1"})
    other = client.post("/quote-request", data=QUOTE_FORM, environ_base={"REMOTE_ADDR": "10.0.0.2"})

    assert client.post(
        "/quote-request", data=QUOTE_FORM, environ_base={"REMOTE_ADDR": "10.0.0.1"}
    ).status_code == 429
    assert blocked.status_code != 429
    assert other.status_code != 429


def test_forwarded_for_header_is_used_behind_a_proxy(app, client):
    app.config.update(RATE_LIMIT_ENABLED=True, RATE_LIMIT_FORM_REQUESTS=1, RATE_LIMIT_FORM_WINDOW_SECONDS=600)

    headers = {"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}

    assert client.post("/quote-request", data=QUOTE_FORM, headers=headers).status_code != 429
    assert client.post("/quote-request", data=QUOTE_FORM, headers=headers).status_code == 429


def test_login_is_throttled_separately_from_the_forms(app, client):
    app.config.update(RATE_LIMIT_ENABLED=True, RATE_LIMIT_LOGIN_REQUESTS=1, RATE_LIMIT_LOGIN_WINDOW_SECONDS=300)

    first = client.post("/admin", data={"email": "nobody@example.test", "password": "wrong"})
    second = client.post("/admin", data={"email": "nobody@example.test", "password": "wrong"})
    form = client.post("/quote-request", data=QUOTE_FORM)

    assert first.status_code != 429
    assert second.status_code == 429
    assert form.status_code != 429, "the login bucket must not throttle the public form"


def test_get_requests_are_never_limited(app, client):
    app.config.update(RATE_LIMIT_ENABLED=True, RATE_LIMIT_FORM_REQUESTS=1)

    assert client.get("/quote-request").status_code == 200
    assert client.get("/quote-request").status_code == 200
    assert client.get("/quote-request").status_code == 200


def test_the_limiter_can_be_switched_off(app, client):
    app.config.update(RATE_LIMIT_ENABLED=False, RATE_LIMIT_FORM_REQUESTS=1)

    for _ in range(4):
        assert client.post("/quote-request", data=QUOTE_FORM).status_code != 429


def test_upload_cap_is_configured(app):
    assert app.config["MAX_CONTENT_LENGTH"] == 25 * 1024 * 1024

"""Reverse-proxy header handling behind nginx."""

from __future__ import annotations

import app.config as config_module
from app import create_app


def _app_with_proxy(monkeypatch, trusted: bool):
    monkeypatch.setattr(config_module.TestingConfig, "TRUST_PROXY", trusted, raising=False)
    app = create_app("testing", {"TENANT_DEFAULT_HOSTS": ("localhost", "customer.example.com")})
    app.config.update(SECRET_KEY="***", WTF_CSRF_ENABLED=False)

    @app.route("/__whoami")
    def _whoami():  # noqa: ANN202 - test-only probe
        from flask import request

        return {
            "remote_addr": request.remote_addr,
            "scheme": request.scheme,
            "host": request.host,
        }

    return app


def test_headers_are_not_trusted_by_default(app):
    assert app.wsgi_app.__class__.__name__ != "ProxyFix"


def test_forwarded_address_is_ignored_without_trust(monkeypatch):
    app = _app_with_proxy(monkeypatch, trusted=False)
    client = app.test_client()

    response = client.get("/__whoami", headers={"X-Forwarded-For": "203.0.113.7"})

    assert response.get_json()["remote_addr"] in ("127.0.0.1", "localhost")


def test_forwarded_address_is_used_when_trusted(monkeypatch):
    app = _app_with_proxy(monkeypatch, trusted=True)
    client = app.test_client()

    response = client.get(
        "/__whoami",
        headers={
            "X-Forwarded-For": "203.0.113.7",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "customer.example.com",
        },
    )

    payload = response.get_json()
    assert payload["remote_addr"] == "203.0.113.7"
    assert payload["scheme"] == "https"
    assert payload["host"] == "customer.example.com"

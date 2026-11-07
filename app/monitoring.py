"""Minimal platform health and privacy-conscious exception reporting."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from flask import Flask, current_app, g, got_request_exception, has_request_context, jsonify, request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname, "logger": record.name, "message": record.getMessage(),
        }
        if has_request_context():
            event["request_id"] = getattr(g, "request_id", None)
            event["tenant"] = getattr(getattr(g, "tenant", None), "slug", None)
        if record.exc_info and record.exc_info[0]:
            event["exception_type"] = record.exc_info[0].__name__
        for key in ("event", "target_tenant", "outcome", "actor"):
            if hasattr(record, key):
                event[key] = getattr(record, key)
        return json.dumps(event)


def report_exception(exception: BaseException) -> bool:
    """Send only exception type and scope; never send customer data or credentials."""
    url = current_app.config.get("ERROR_WEBHOOK_URL", "")
    if not url:
        return False
    payload = {"event": "application_exception", "exception_type": type(exception).__name__}
    if has_request_context():
        payload["request_id"] = getattr(g, "request_id", None)
    payload["tenant"] = getattr(getattr(g, "tenant", None), "slug", None)
    notification = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(notification, timeout=3) as response:
            if not 200 <= response.status < 300:
                raise URLError("Unexpected webhook status")
    except (URLError, OSError, ValueError):
        current_app.logger.error("Exception reporting delivery failed.")
        return False
    return True


def register_monitoring(app: Flask) -> None:
    url = app.config.get("ERROR_WEBHOOK_URL", "")
    if url:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("ERROR_WEBHOOK_URL must be an HTTPS URL without credentials or a fragment.")
    if not app.debug and not app.testing:
        for handler in app.logger.handlers:
            handler.setFormatter(JsonFormatter())
        app.logger.setLevel(logging.INFO)

    @app.before_request
    def request_identifier():
        g.request_id = uuid4().hex

    @app.after_request
    def log_response(response):
        response.headers["X-Request-ID"] = g.request_id
        if not app.debug and not app.testing:
            app.logger.info("request endpoint=%s status=%s", request.endpoint, response.status_code)
        return response

    def capture(sender, exception, **extra):
        report_exception(exception)
    got_request_exception.connect(capture, app, weak=False)

    @app.get("/healthz")
    def healthz():
        if request.args.get("db") == "1":
            from app.extensions import db
            try:
                db.session.execute(text("select 1"))
            except SQLAlchemyError:
                app.logger.exception("Tenant health database check failed.")
                return jsonify(status="unavailable"), 503
        return jsonify(status="ok")

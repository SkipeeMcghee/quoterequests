"""In-app rate limiting for the endpoints an anonymous visitor can POST to.

Deliberately small: a fixed-window counter held in memory, keyed by tenant, client IP,
and a named bucket. No dependency, no Redis.

Two honest limitations, both documented in the deployment checklist:

* Counters live in the process. With several gunicorn workers each one keeps its own
  tally, so the effective limit is roughly `workers x limit`. Run one worker, or treat
  this as a spam speed bump alongside reCAPTCHA rather than a hard security boundary.
* Counters reset when the app restarts.

That is the right trade for a single small business site. If a deployment ever needs
exact limits, swap the `_STORE` for a Redis-backed counter without touching the callers.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from flask import request

from app.tenancy import current_tenant_settings, get_current_tenant, tenant_config


@dataclass(frozen=True)
class Limit:
    max_requests: int
    window_seconds: int


# bucket -> endpoint(s) it applies to. Anything not listed is not limited.
RULES: dict[str, tuple[Limit, tuple[str, ...]]] = {}


class _FixedWindowStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, tuple[float, int]] = {}

    def hit(self, key: str, window_seconds: int) -> int:
        """Record a hit and return the count inside the current window."""

        now = time.monotonic()
        with self._lock:
            expires, count = self._hits.get(key, (now + window_seconds, 0))
            if now >= expires:
                expires, count = now + window_seconds, 0
            count += 1
            self._hits[key] = (expires, count)
            if len(self._hits) > 5000:  # keep a runaway keyspace from growing forever
                self._hits = {
                    key_: value for key_, value in self._hits.items() if now < value[0]
                }
            return count

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_STORE = _FixedWindowStore()


def reset_all() -> None:
    """Test hook."""

    _STORE.reset()


def client_key() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        # The first entry is the original client when a reverse proxy appends.
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def limits_from_config() -> dict[str, Limit]:
    config = current_tenant_settings()
    return {
        "forms": Limit(
            int(config.get("RATE_LIMIT_FORM_REQUESTS") or 5),
            int(config.get("RATE_LIMIT_FORM_WINDOW_SECONDS") or 600),
        ),
        "login": Limit(
            int(config.get("RATE_LIMIT_LOGIN_REQUESTS") or 10),
            int(config.get("RATE_LIMIT_LOGIN_WINDOW_SECONDS") or 300),
        ),
    }


FORM_ENDPOINTS = {
    "main.quote_request",
    "main.schedule_work",
}

LOGIN_ENDPOINTS = {
    "admin.admin_entry",
    "auth.login",
}


def bucket_for(endpoint: str) -> str | None:
    if endpoint in FORM_ENDPOINTS:
        return "forms"
    if endpoint in LOGIN_ENDPOINTS:
        return "login"
    return None


def check_rate_limit() -> tuple[int, int] | None:
    """Return (retry_after_seconds, limit) when the caller is over, else None."""

    if request.endpoint == "healthz":
        return None
    if not tenant_config("RATE_LIMIT_ENABLED", True):
        return None
    if request.method != "POST":
        return None

    bucket = bucket_for(request.endpoint or "")
    if bucket is None:
        return None

    limit = limits_from_config()[bucket]
    key = f"{get_current_tenant().slug}:{bucket}:{client_key()}"
    count = _STORE.hit(key, limit.window_seconds)

    if count > limit.max_requests:
        return limit.window_seconds, limit.max_requests
    return None

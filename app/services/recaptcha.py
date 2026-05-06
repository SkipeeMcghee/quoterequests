from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from flask import current_app


DEFAULT_RECAPTCHA_ERROR = "We couldn't verify the spam protection check. Please try again."
MISSING_TOKEN_ERROR = "Complete the spam protection check and try again."
MISCONFIGURED_RECAPTCHA_ERROR = "reCAPTCHA is enabled but not fully configured."


@dataclass(frozen=True)
class RecaptchaVerificationResult:
    success: bool
    message: str = ""
    score: float | None = None
    action: str = ""


def is_recaptcha_enabled(config: Mapping[str, object] | None = None) -> bool:
    settings = config or current_app.config
    return bool(settings.get("RECAPTCHA_ENABLED", False))


def should_render_recaptcha(config: Mapping[str, object] | None = None) -> bool:
    settings = config or current_app.config
    site_key = str(settings.get("RECAPTCHA_SITE_KEY", "")).strip()
    return is_recaptcha_enabled(settings) and bool(site_key)


def verify_recaptcha_submission(token: str, action: str, remote_ip: str | None = None) -> RecaptchaVerificationResult:
    if not is_recaptcha_enabled():
        return RecaptchaVerificationResult(success=True)

    if not token.strip():
        return RecaptchaVerificationResult(success=False, message=MISSING_TOKEN_ERROR)

    secret_key = str(current_app.config.get("RECAPTCHA_SECRET_KEY", "")).strip()
    verify_url = str(current_app.config.get("RECAPTCHA_VERIFY_URL", "")).strip()
    minimum_score = float(current_app.config.get("RECAPTCHA_MIN_SCORE", 0.5))
    if not secret_key or not verify_url:
        return RecaptchaVerificationResult(success=False, message=MISCONFIGURED_RECAPTCHA_ERROR)

    payload = {
        "secret": secret_key,
        "response": token.strip(),
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        with urlopen(verify_url, urlencode(payload).encode("utf-8"), timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError):
        return RecaptchaVerificationResult(success=False, message=DEFAULT_RECAPTCHA_ERROR)

    if not body.get("success"):
        return RecaptchaVerificationResult(success=False, message=DEFAULT_RECAPTCHA_ERROR)

    verified_action = str(body.get("action", "")).strip()
    if verified_action != action:
        return RecaptchaVerificationResult(success=False, message=DEFAULT_RECAPTCHA_ERROR)

    try:
        score = float(body.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0

    if score < minimum_score:
        return RecaptchaVerificationResult(success=False, message=DEFAULT_RECAPTCHA_ERROR, score=score, action=verified_action)

    return RecaptchaVerificationResult(success=True, score=score, action=verified_action)
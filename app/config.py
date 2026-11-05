from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)

DEFAULT_SITE_LOGO_PATH = "assets/images/Logowhite.png"

SOCIAL_PLATFORM_ASSETS: dict[str, dict[str, str]] = {
    "facebook": {"label": "Facebook", "icon_path": "assets/images/facebook.png"},
    "instagram": {"label": "Instagram", "icon_path": "assets/images/instagram.png"},
    "linkedin": {"label": "LinkedIn", "icon_path": "assets/images/linkedin.png"},
    "youtube": {"label": "YouTube", "icon_path": "assets/images/youtube.png"},
    "x": {"label": "X", "icon_path": "assets/images/x.png"},
    "tiktok": {"label": "TikTok", "icon_path": "assets/images/tiktok.png"},
    "pinterest": {"label": "Pinterest", "icon_path": "assets/images/pinterest.png"},
    "whatsapp": {"label": "WhatsApp", "icon_path": "assets/images/whatsapp.png"},
    "telegram": {"label": "Telegram", "icon_path": "assets/images/telegram.png"},
    "skype": {"label": "Skype", "icon_path": "assets/images/skype.png"},
    "snapchat": {"label": "Snapchat", "icon_path": "assets/images/snapchat.png"},
    "spotify": {"label": "Spotify", "icon_path": "assets/images/spotify.png"},
    "reddit": {"label": "Reddit", "icon_path": "assets/images/reddit.png"},
    "google": {"label": "Google Business", "icon_path": "assets/images/google.png"},
}

TENANT_BOOLEAN_SETTINGS = frozenset({
    "ENABLE_SERVICES", "ENABLE_GALLERY", "ENABLE_SCHEDULING", "ENABLE_STAFF_MANAGEMENT",
    "ENABLE_CUSTOMER_RECORDS", "ENABLE_CALENDAR", "ENABLE_RECURRING_WORK",
    "EMAIL_ENABLED", "SMTP_USE_TLS", "SMTP_USE_SSL", "RECAPTCHA_ENABLED",
    "SOCIAL_LINKS_PREVIEW", "RATE_LIMIT_ENABLED",
    *(f"SOCIAL_{platform.upper()}_ENABLED" for platform in SOCIAL_PLATFORM_ASSETS),
})
TENANT_INTEGER_SETTINGS = frozenset({
    "SMTP_PORT", "SMTP_TIMEOUT", "RATE_LIMIT_FORM_REQUESTS", "RATE_LIMIT_FORM_WINDOW_SECONDS",
    "RATE_LIMIT_LOGIN_REQUESTS", "RATE_LIMIT_LOGIN_WINDOW_SECONDS",
})
TENANT_STRING_SETTINGS = frozenset({
    "BUSINESS_NAME", "COMPANY_NAME", "TAGLINE", "BUSINESS_PHONE", "BUSINESS_EMAIL",
    "SERVICE_AREA", "BUSINESS_ADDRESS", "STAFF_COMPENSATION_CURRENCY", "COMPENSATION_CURRENCY",
    "SITE_LOGO_PATH", "SITE_LOGO_ALT", "SITE_THEME", "CANONICAL_ORIGIN",
    "ADMIN_NOTIFICATION_EMAIL", "DEFAULT_FROM_EMAIL", "EMAIL_FROM_NAME", "EMAIL_REPLY_TO",
    "SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "RECAPTCHA_SITE_KEY",
    "RECAPTCHA_SECRET_KEY", "RECAPTCHA_VERIFY_URL",
    *(f"SOCIAL_{platform.upper()}_URL" for platform in SOCIAL_PLATFORM_ASSETS),
})
TENANT_SETTING_KEYS = (
    TENANT_BOOLEAN_SETTINGS | TENANT_INTEGER_SETTINGS | TENANT_STRING_SETTINGS
    | {"RECAPTCHA_MIN_SCORE", "SITE_LOGO", "SOCIAL_LINKS"}
)


def normalize_canonical_origin(value: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    if (
        any(char.isspace() or char == "\\" for char in value)
        or parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.path not in ("", "/") or parsed.query or parsed.fragment
    ):
        raise ValueError("CANONICAL_ORIGIN must be an HTTPS origin without credentials or a path.")
    hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    hostname = f"[{hostname}]" if ":" in hostname else hostname
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"https://{hostname}{port}"


def validate_tenant_settings(settings: Mapping[str, Any]) -> None:
    for key, value in settings.items():
        if key not in TENANT_SETTING_KEYS:
            raise ValueError(f"Unsupported tenant setting: {key}")
        if key in TENANT_BOOLEAN_SETTINGS:
            valid = isinstance(value, bool)
        elif key in TENANT_INTEGER_SETTINGS:
            valid = type(value) is int and value > 0 and (key != "SMTP_PORT" or value <= 65535)
        elif key == "RECAPTCHA_MIN_SCORE":
            valid = type(value) in (int, float) and 0 <= value <= 1
        elif key in ("SITE_LOGO", "SOCIAL_LINKS"):
            if not isinstance(value, Mapping):
                raise ValueError(f"Tenant {key} must be a mapping.")
            if key == "SITE_LOGO":
                valid = all(name in ("path", "alt") and isinstance(item, str) for name, item in value.items())
            else:
                valid = all(
                    isinstance(platform, str) and isinstance(link, Mapping) and all(
                        (name == "enabled" and isinstance(item, bool))
                        or (name in ("url", "label", "icon_path") and isinstance(item, str))
                        for name, item in link.items()
                    )
                    for platform, link in value.items()
                )
        else:
            valid = isinstance(value, str)
        if not valid:
            raise ValueError(f"Invalid value type or range for tenant setting {key}.")
        if key == "CANONICAL_ORIGIN":
            normalize_canonical_origin(value)


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    raise RuntimeError(f"Missing required environment variable: {name}")


def parse_csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(name, "")
    if not raw_value:
        return default

    values = tuple(item.strip() for item in raw_value.split(",") if item.strip())
    return values or default


def parse_bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in ("1", "true", "yes", "on")


def parse_float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = float(raw_value)
    except ValueError:
        return default

    return max(0.0, min(1.0, value))


def normalize_static_asset_path(value: str, default: str = "") -> str:
    normalized = (value or default).strip().lstrip("/")
    return normalized or default


def build_social_links() -> dict[str, dict[str, str | bool]]:
    social_links: dict[str, dict[str, str | bool]] = {}
    for platform, defaults in SOCIAL_PLATFORM_ASSETS.items():
        env_prefix = f"SOCIAL_{platform.upper()}"
        social_links[platform] = {
            **defaults,
            "enabled": parse_bool_env(f"{env_prefix}_ENABLED", False),
            "url": os.getenv(f"{env_prefix}_URL", "").strip(),
        }
    return social_links


class Config:
    TENANTS = None
    TENANTS_JSON = os.getenv("TENANTS_JSON", "")
    TENANT_REGISTRY_FILE = os.getenv("TENANT_REGISTRY_FILE", "")
    TENANT_ALLOW_DEFAULT = False
    TENANT_DEFAULT_HOSTS = ("localhost", "127.0.0.1", "[::1]")
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    WTF_CSRF_TIME_LIMIT = 8 * 60 * 60
    RECAPTCHA_ENABLED = parse_bool_env("RECAPTCHA_ENABLED", False)
    RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY", "").strip()
    RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY", "").strip()
    RECAPTCHA_MIN_SCORE = parse_float_env("RECAPTCHA_MIN_SCORE", 0.5)
    RECAPTCHA_VERIFY_URL = os.getenv(
        "RECAPTCHA_VERIFY_URL",
        "https://www.google.com/recaptcha/api/siteverify",
    ).strip()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024
    UPLOAD_FOLDER = str(BASE_DIR / "app" / "static" / "uploads")
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
    ENABLE_GALLERY = parse_bool_env("ENABLE_GALLERY", False)
    ENABLE_SERVICES = parse_bool_env("ENABLE_SERVICES", False)
    ENABLE_SCHEDULING = os.getenv("ENABLE_SCHEDULING", "false").lower() in ("1", "true", "yes")
    ENABLE_STAFF_MANAGEMENT = os.getenv("ENABLE_STAFF_MANAGEMENT", "false").lower() in ("1", "true", "yes")
    ENABLE_CUSTOMER_RECORDS = os.getenv("ENABLE_CUSTOMER_RECORDS", "false").lower() in ("1", "true", "yes")
    ENABLE_CALENDAR = os.getenv("ENABLE_CALENDAR", "false").lower() in ("1", "true", "yes")
    ENABLE_RECURRING_WORK = os.getenv("ENABLE_RECURRING_WORK", "false").lower() in ("1", "true", "yes")
    BUSINESS_NAME = os.getenv("BUSINESS_NAME") or os.getenv("COMPANY_NAME", "Service Company")
    COMPANY_NAME = BUSINESS_NAME
    TAGLINE = os.getenv("TAGLINE", "Clear estimates and straightforward service.")
    BUSINESS_PHONE = os.getenv("BUSINESS_PHONE", "(555) 010-0200")
    BUSINESS_EMAIL = os.getenv("BUSINESS_EMAIL", "hello@example.com")
    SERVICE_AREA = os.getenv("SERVICE_AREA", "your local service area")
    BUSINESS_ADDRESS = os.getenv("BUSINESS_ADDRESS", "123 Service Lane, Suite 100")
    STAFF_COMPENSATION_CURRENCY = (
        (os.getenv("STAFF_COMPENSATION_CURRENCY") or os.getenv("COMPENSATION_CURRENCY", "USD")).strip() or "USD"
    ).upper()
    COMPENSATION_CURRENCY = STAFF_COMPENSATION_CURRENCY
    CANONICAL_ORIGIN = os.getenv("CANONICAL_ORIGIN", "").strip()
    SITE_THEME = os.getenv("SITE_THEME", "").strip()
    SITE_LOGO = {
        "path": normalize_static_asset_path(os.getenv("SITE_LOGO_PATH", DEFAULT_SITE_LOGO_PATH), DEFAULT_SITE_LOGO_PATH),
        "alt": os.getenv("SITE_LOGO_ALT", "").strip(),
    }
    SOCIAL_LINKS_PREVIEW = parse_bool_env("SOCIAL_LINKS_PREVIEW", False)
    SOCIAL_LINKS = build_social_links()
    ADMIN_NOTIFICATION_EMAIL = os.getenv("ADMIN_NOTIFICATION_EMAIL", "admin@example.com")
    DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", BUSINESS_EMAIL)

    # Transactional email. Off unless configured, so a fresh install never tries to
    # talk to a mail server. Brevo: SMTP_HOST=smtp-relay.brevo.com, SMTP_PORT=587,
    # SMTP_USERNAME=<login>, SMTP_PASSWORD=<SMTP key>.
    EMAIL_ENABLED = parse_bool_env("EMAIL_ENABLED", False)
    SMTP_HOST = (os.getenv("SMTP_HOST", "") or "").strip()
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or 587)
    SMTP_USERNAME = (os.getenv("SMTP_USERNAME", "") or "").strip()
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS = parse_bool_env("SMTP_USE_TLS", True)
    SMTP_USE_SSL = parse_bool_env("SMTP_USE_SSL", False)
    SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "10") or 10)
    EMAIL_FROM_NAME = (os.getenv("EMAIL_FROM_NAME", "") or BUSINESS_NAME).strip()
    EMAIL_REPLY_TO = (os.getenv("EMAIL_REPLY_TO", "") or "").strip()
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    # Set true only when nginx (or another reverse proxy) sits in front and sets
    # X-Forwarded-For/Proto. Off by default so a client cannot spoof its own address.
    TRUST_PROXY = parse_bool_env("TRUST_PROXY", False)

    # Anonymous-form throttling. Counters are per process; see app/services/rate_limit.py.
    RATE_LIMIT_ENABLED = parse_bool_env("RATE_LIMIT_ENABLED", True)
    RATE_LIMIT_FORM_REQUESTS = int(os.getenv("RATE_LIMIT_FORM_REQUESTS", "5") or 5)
    RATE_LIMIT_FORM_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_FORM_WINDOW_SECONDS", "600") or 600)
    RATE_LIMIT_LOGIN_REQUESTS = int(os.getenv("RATE_LIMIT_LOGIN_REQUESTS", "10") or 10)
    RATE_LIMIT_LOGIN_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_LOGIN_WINDOW_SECONDS", "300") or 300)

    @staticmethod
    def validate() -> None:
        return None


class DevelopmentConfig(Config):
    TENANT_ALLOW_DEFAULT = True
    DEBUG = True
    ENABLE_GALLERY = parse_bool_env("ENABLE_GALLERY", False)
    ENABLE_SERVICES = parse_bool_env("ENABLE_SERVICES", True)
    ENABLE_SCHEDULING = parse_bool_env("ENABLE_SCHEDULING", True)
    ENABLE_STAFF_MANAGEMENT = parse_bool_env("ENABLE_STAFF_MANAGEMENT", True)
    ENABLE_CUSTOMER_RECORDS = parse_bool_env("ENABLE_CUSTOMER_RECORDS", True)
    ENABLE_CALENDAR = parse_bool_env("ENABLE_CALENDAR", True)
    ENABLE_RECURRING_WORK = parse_bool_env("ENABLE_RECURRING_WORK", True)
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://quote_requests:quote_requests@localhost:5432/quote_requests",
    )


class TestingConfig(Config):
    TENANT_ALLOW_DEFAULT = True
    TENANTS_JSON = ""
    TENANT_REGISTRY_FILE = ""
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATE_LIMIT_ENABLED = False
    SOCIAL_LINKS_PREVIEW = False
    ENABLE_GALLERY = False
    ENABLE_SERVICES = False
    ENABLE_SCHEDULING = False
    ENABLE_STAFF_MANAGEMENT = False
    ENABLE_CUSTOMER_RECORDS = False
    ENABLE_CALENDAR = False
    ENABLE_RECURRING_WORK = False
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True

    @staticmethod
    def validate() -> None:
        get_required_env("DATABASE_URL")
        secret_key = get_required_env("SECRET_KEY")
        if secret_key == "change-me":
            raise RuntimeError("SECRET_KEY must be changed for production.")
        if parse_bool_env("RECAPTCHA_ENABLED", False):
            get_required_env("RECAPTCHA_SITE_KEY")
            get_required_env("RECAPTCHA_SECRET_KEY")


config_by_name = {
    "default": DevelopmentConfig,
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
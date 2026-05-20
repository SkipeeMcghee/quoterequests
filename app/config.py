from __future__ import annotations

import os
from pathlib import Path

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
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024
    UPLOAD_FOLDER = str(BASE_DIR / "app" / "static" / "uploads")
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
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
    STAFF_COMPENSATION_CURRENCY = (os.getenv("STAFF_COMPENSATION_CURRENCY", "USD").strip() or "USD").upper()
    SITE_LOGO = {
        "path": normalize_static_asset_path(os.getenv("SITE_LOGO_PATH", DEFAULT_SITE_LOGO_PATH), DEFAULT_SITE_LOGO_PATH),
        "alt": os.getenv("SITE_LOGO_ALT", "").strip(),
    }
    SOCIAL_LINKS_PREVIEW = parse_bool_env("SOCIAL_LINKS_PREVIEW", False)
    SOCIAL_LINKS = build_social_links()
    ADMIN_NOTIFICATION_EMAIL = os.getenv("ADMIN_NOTIFICATION_EMAIL", "admin@example.com")
    DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", BUSINESS_EMAIL)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    @staticmethod
    def validate() -> None:
        return None


class DevelopmentConfig(Config):
    DEBUG = True
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
    TESTING = True
    WTF_CSRF_ENABLED = False
    SOCIAL_LINKS_PREVIEW = False
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
from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_BUSINESS_SERVICES = (
    "Landscape Design",
    "Roof Repair",
    "Window Cleaning",
    "Inspection",
    "Painting",
    "Deck Staining",
    "Flooring",
    "Siding",
    "Fence Repair",
    "General Maintenance",
)


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


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024
    UPLOAD_FOLDER = str(BASE_DIR / "app" / "static" / "uploads")
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
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
    BUSINESS_SERVICES = parse_csv_env("BUSINESS_SERVICES", DEFAULT_BUSINESS_SERVICES)
    BUSINESS_SERVICES_OVERRIDDEN = bool(os.getenv("BUSINESS_SERVICES"))
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
    ENABLE_SCHEDULING = True
    ENABLE_STAFF_MANAGEMENT = True
    ENABLE_CUSTOMER_RECORDS = True
    ENABLE_CALENDAR = True
    ENABLE_RECURRING_WORK = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://quote_requests:quote_requests@localhost:5432/quote_requests",
    )


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
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


config_by_name = {
    "default": DevelopmentConfig,
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
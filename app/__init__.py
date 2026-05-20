from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template_string, request, url_for
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import RequestEntityTooLarge

from app.auth import bp as auth_bp
from app.config import config_by_name
from app.extensions import csrf, db, login_manager, migrate
from app.main import bp as main_bp
from app.admin import bp as admin_bp
from app.cli import register_cli
from app.services.service_catalog import list_active_services


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    config_object = config_by_name[config_name or "default"]
    app.config.from_object(config_object)
    config_object.validate()

    _ensure_runtime_directories(app)

    register_extensions(app)
    register_models()
    register_blueprints(app)
    register_legacy_admin_routes(app)
    register_login_manager()
    register_context_processors(app)
    register_error_handlers(app)
    register_cli(app)

    return app


def register_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)


def register_models() -> None:
    from app import models  # noqa: F401


def register_legacy_admin_routes(app: Flask) -> None:
    def admin_entry_target() -> str:
        next_url = request.args.get("next")
        if next_url:
            return url_for("admin.admin_entry", next=next_url)
        return url_for("admin.admin_entry")

    @app.get("/login")
    def legacy_login_redirect():
        return redirect(admin_entry_target())

    @app.get("/dashboard/login")
    def legacy_dashboard_login_redirect():
        return redirect(admin_entry_target())


def register_login_manager() -> None:
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        return db.session.get(User, int(user_id))


def _get_site_services(app: Flask):
    return list_active_services()


def _get_enabled_social_links(app: Flask) -> list[dict[str, str | bool]]:
    configured_links = app.config.get("SOCIAL_LINKS", {})
    preview_mode = app.config.get("SOCIAL_LINKS_PREVIEW", False)
    enabled_links: list[dict[str, str | bool]] = []
    for platform, settings in configured_links.items():
        if not isinstance(settings, dict):
            continue

        is_enabled = bool(settings.get("enabled"))
        url = str(settings.get("url", "")).strip()

        if is_enabled and url:
            enabled_links.append(
                {
                    "platform": platform,
                    "label": str(settings.get("label", platform.title())),
                    "url": url,
                    "icon_path": str(settings.get("icon_path", "")),
                    "is_preview": False,
                }
            )
            continue

        if not preview_mode:
            continue

        enabled_links.append(
            {
                "platform": platform,
                "label": str(settings.get("label", platform.title())),
                "url": "",
                "icon_path": str(settings.get("icon_path", "")),
                "is_preview": True,
            }
        )

    return enabled_links


def _describe_service(service_name) -> str:
    if hasattr(service_name, "normalized_description") and service_name.normalized_description:
        return service_name.normalized_description

    if hasattr(service_name, "name"):
        service_name = service_name.name

    descriptions = {
        "landscape design": "Planning plantings, layout changes, and outdoor improvements that fit the property and how you use it.",
        "roof repair": "Targeted repairs and condition reviews that help address small roofing issues before they become larger ones.",
        "window cleaning": "Interior and exterior window cleaning with attention to access, finish, and the condition of surrounding trim.",
        "inspection": "On-site assessments that identify visible issues, answer questions, and clarify the right next step.",
        "painting": "Interior and exterior painting support focused on careful prep, clean lines, and durable results.",
        "deck staining": "Cleaning, prep, and stain application that helps protect exposed wood and refresh the look of the deck.",
        "flooring": "Flooring updates and repair work with clear scope, material planning, and finish expectations.",
        "siding": "Siding repair and upkeep that helps the exterior look cared for and stay weather ready.",
        "fence repair": "Fence repairs that address stability, alignment, and worn sections without overcomplicating the job.",
        "general maintenance": "Small repairs and recurring upkeep for homes and properties that need dependable follow-through.",
    }
    normalized_name = service_name.strip().lower()
    fallback_name = normalized_name or "general service"
    return descriptions.get(
        normalized_name,
        f"Clear recommendations, dependable scheduling, and straightforward communication for {fallback_name} work.",
    )


def register_context_processors(app: Flask) -> None:
    @app.context_processor
    def inject_feature_flags() -> dict[str, object]:
        return {
            "enable_services": app.config.get("ENABLE_SERVICES", False),
            "enable_scheduling": app.config.get("ENABLE_SCHEDULING", False),
            "enable_staff_management": app.config.get("ENABLE_STAFF_MANAGEMENT", False),
            "enable_customer_records": app.config.get("ENABLE_CUSTOMER_RECORDS", False),
            "enable_calendar": app.config.get("ENABLE_CALENDAR", False),
            "enable_recurring_work": app.config.get("ENABLE_RECURRING_WORK", False),
            "business_name": app.config.get("BUSINESS_NAME", app.config.get("COMPANY_NAME", "Service Company")),
            "tagline": app.config.get("TAGLINE", ""),
            "phone": app.config.get("BUSINESS_PHONE", ""),
            "email": app.config.get("BUSINESS_EMAIL", ""),
            "service_area": app.config.get("SERVICE_AREA", ""),
            "address": app.config.get("BUSINESS_ADDRESS", ""),
            "staff_compensation_currency": app.config.get("STAFF_COMPENSATION_CURRENCY", "USD"),
            "site_logo": app.config.get("SITE_LOGO", {}),
            "social_links": app.config.get("SOCIAL_LINKS", {}),
            "enabled_social_links": _get_enabled_social_links(app),
            "services": _get_site_services(app),
            "describe_service": _describe_service,
        }


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(CSRFError)
    def handle_csrf_error(error: CSRFError):
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "error": "That page sat too long and its security token expired. Reload and try again."}), 400

        flash("That page sat too long and its security token expired. Reload and try again.", "error")
        return redirect(request.referrer or url_for("main.index"))

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_entity_too_large(error: RequestEntityTooLarge):
        return render_template_string(
            """<!doctype html>
            <html lang=\"en\">
              <head>
                <meta charset=\"utf-8\">
                <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
                <title>Upload too large</title>
              </head>
              <body>
                <div class=\"page-shell\">
                  <section class=\"section-intro\">
                    <h1>Upload too large</h1>
                    <p>The total upload size exceeds the configured limit. Try smaller files or fewer photos.</p>
                    <p><a href=\"{{ url_for('main.quote_request') }}\">Back to request form</a></p>
                  </section>
                </div>
              </body>
            </html>""",
            error=error,
        ), 413


def _ensure_runtime_directories(app: Flask) -> None:
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
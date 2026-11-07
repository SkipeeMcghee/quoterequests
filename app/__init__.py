from pathlib import Path
from collections.abc import Mapping
from posixpath import normpath

from flask import Flask, abort, flash, g, jsonify, make_response, redirect, render_template, render_template_string, request, url_for
from flask_login import current_user
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import RequestEntityTooLarge

from app.auth import bp as auth_bp
from app.config import config_by_name
from app.extensions import csrf, db, login_manager, migrate, teardown_tenant_request
from app.main import bp as main_bp
from app.admin import bp as admin_bp
from app.cli import register_cli
from app.services.gallery_catalog import has_public_gallery_items
from app.services.service_catalog import list_active_services
from app.services.themes import (
    css_variables,
    display_name as theme_display_name,
    get_active_slug as get_active_theme_slug,
)
from app.services.media import media_url
from app.tenancy import current_tenant_settings, get_registry, is_default_tenant, register_tenancy


def create_app(config_name: str | None = None, config_overrides: Mapping[str, object] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    config_object = config_by_name[config_name or "default"]
    app.config.from_object(config_object)
    if config_overrides is not None:
        app.config.update(config_overrides)
    config_object.validate()

    register_proxy_fix(app)
    from app.monitoring import register_monitoring
    register_monitoring(app)
    register_tenancy(app)
    _ensure_runtime_directories(app)
    register_extensions(app)
    register_models()
    register_blueprints(app)
    register_legacy_admin_routes(app)
    register_login_manager()
    register_context_processors(app)
    register_private_upload_guard(app)
    register_rate_limiting(app)
    register_error_handlers(app)
    register_cli(app)

    return app


def register_extensions(app: Flask) -> None:
    db.init_app(app)
    with app.app_context():
        get_registry().bind_engines(app, db.engine)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    app.teardown_request(teardown_tenant_request)


def register_blueprints(app: Flask) -> None:
    from app.superadmin import bp as superadmin_bp
    app.register_blueprint(superadmin_bp, url_prefix=app.config["SUPERADMIN_PATH"])
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
    from app.services.auth import load_tenant_user

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        return load_tenant_user(user_id)


def _get_site_services(app: Flask):
    return list_active_services()


def _get_enabled_social_links(app: Flask) -> list[dict[str, str | bool]]:
    tenant_settings = current_tenant_settings()
    configured_links = tenant_settings.get("SOCIAL_LINKS", {})
    preview_mode = tenant_settings.get("SOCIAL_LINKS_PREVIEW", False)
    enabled_links: list[dict[str, str | bool]] = []
    for platform, settings in configured_links.items():
        if not isinstance(settings, Mapping):
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


def register_private_upload_guard(app: Flask) -> None:
    """Block shared static uploads, retaining only the default tenant's public gallery."""

    from app.services.media import is_private_upload

    @app.before_request
    def block_public_uploads():
        if request.endpoint != "static":
            return
        filename = str((request.view_args or {}).get("filename", ""))
        filename = filename.replace("\\", "/")
        # Windows aliases trailing dots/spaces to otherwise distinct path names.
        if any(part not in (".", "..") and part.endswith((".", " ")) for part in filename.split("/")):
            abort(404)
        normalized = normpath(filename).lstrip("/").casefold()
        if normalized == "uploads" or normalized.startswith("uploads/"):
            if not is_default_tenant() or is_private_upload(normalized):
                abort(404)


def register_proxy_fix(app: Flask) -> None:
    """Trust one layer of reverse-proxy headers when TRUST_PROXY is on.

    nginx terminates TLS and forwards X-Forwarded-For/Proto/Host. Without this the app
    thinks every request came from 127.0.0.1 over http, which breaks per-client rate
    limiting and secure-cookie checks. Off by default: trusting these headers without a
    proxy in front lets a client spoof its own address.
    """

    if not app.config.get("TRUST_PROXY"):
        return

    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)


def register_rate_limiting(app: Flask) -> None:
    """Throttle the two anonymous POST endpoints and the login form."""

    from app.services.rate_limit import check_rate_limit

    @app.before_request
    def enforce_rate_limits():
        if getattr(g, "platform_control", False):
            return None  # Dedicated platform login limiter runs before CSRF.
        verdict = check_rate_limit()
        if verdict is None:
            return None
        retry_after, _limit = verdict
        response = make_response(render_template("errors/429.html", retry_after=retry_after), 429)
        response.headers["Retry-After"] = str(retry_after)
        return response


def register_context_processors(app: Flask) -> None:
    @app.context_processor
    def inject_feature_flags() -> dict[str, object]:
        if getattr(g, "platform_control", False):
            return {}
        settings = current_tenant_settings()
        return {
            "enable_gallery": settings.get("ENABLE_GALLERY", False),
            "enable_services": settings.get("ENABLE_SERVICES", False),
            "enable_scheduling": settings.get("ENABLE_SCHEDULING", False),
            "enable_staff_management": settings.get("ENABLE_STAFF_MANAGEMENT", False),
            "enable_customer_records": settings.get("ENABLE_CUSTOMER_RECORDS", False),
            "enable_calendar": settings.get("ENABLE_CALENDAR", False),
            "enable_recurring_work": settings.get("ENABLE_RECURRING_WORK", False),
            "has_public_gallery": has_public_gallery_items(),
            "business_name": settings.get("BUSINESS_NAME", "Service Company"),
            "tagline": settings.get("TAGLINE", ""),
            "phone": settings.get("BUSINESS_PHONE", ""),
            "email": settings.get("BUSINESS_EMAIL", ""),
            "service_area": settings.get("SERVICE_AREA", ""),
            "address": settings.get("BUSINESS_ADDRESS", ""),
            "staff_compensation_currency": settings.get("STAFF_COMPENSATION_CURRENCY", "USD"),
            "site_logo": settings.get("SITE_LOGO", {}),
            "social_links": settings.get("SOCIAL_LINKS", {}),
            "enabled_social_links": _get_enabled_social_links(app),
            "services": _get_site_services(app),
            "describe_service": _describe_service,
            "theme_css": css_variables(get_active_theme_slug(app)),
            "active_theme_name": theme_display_name(get_active_theme_slug(app)),
            "media_url": media_url,
        }


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(CSRFError)
    def handle_csrf_error(error: CSRFError):
        if getattr(g, "platform_control", False):
            from app.superadmin.routes import audit
            audit("csrf", outcome="rejected")
            return "Invalid CSRF token.", 400
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

    @app.errorhandler(404)
    def handle_not_found(error):
        if getattr(g, "platform_control", False):
            return "Not found.", 404
        if request.path.startswith("/admin") and not current_user.is_authenticated:
            return redirect(url_for("admin.admin_entry"))
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def handle_server_error(error):
        app.logger.exception("Unhandled error while serving %s", request.path)
        try:
            return render_template("errors/500.html"), 500
        except Exception:  # noqa: BLE001 - the error page must never raise
            return "Something went wrong. Please try again.", 500


def _ensure_runtime_directories(app: Flask) -> None:
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if app.extensions["tenancy"].default_slug is not None:
        Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
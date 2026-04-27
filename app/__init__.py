from pathlib import Path

from flask import Flask, render_template_string
from werkzeug.exceptions import RequestEntityTooLarge

from app.auth import bp as auth_bp
from app.config import config_by_name
from app.extensions import csrf, db, login_manager, migrate
from app.main import bp as main_bp
from app.admin import bp as admin_bp
from app.cli import register_cli


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    config_object = config_by_name[config_name or "default"]
    app.config.from_object(config_object)
    config_object.validate()

    _ensure_runtime_directories(app)

    register_extensions(app)
    register_models()
    register_blueprints(app)
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


def register_login_manager() -> None:
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:
        return db.session.get(User, int(user_id))


def register_context_processors(app: Flask) -> None:
    @app.context_processor
    def inject_feature_flags() -> dict[str, bool]:
        return {
            "enable_scheduling": app.config.get("ENABLE_SCHEDULING", False),
            "enable_customer_records": app.config.get("ENABLE_CUSTOMER_RECORDS", False),
            "enable_calendar": app.config.get("ENABLE_CALENDAR", False),
            "enable_recurring_work": app.config.get("ENABLE_RECURRING_WORK", False),
        }


def register_error_handlers(app: Flask) -> None:
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
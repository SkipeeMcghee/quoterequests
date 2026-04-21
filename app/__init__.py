from pathlib import Path

from flask import Flask

from app.auth import bp as auth_bp
from app.config import config_by_name
from app.extensions import csrf, db, login_manager, migrate
from app.main import bp as main_bp
from app.admin import bp as admin_bp
from app.cli import register_cli


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_by_name[config_name or "default"])

    _ensure_runtime_directories(app)

    register_extensions(app)
    register_models()
    register_blueprints(app)
    register_login_manager()
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


def _ensure_runtime_directories(app: Flask) -> None:
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
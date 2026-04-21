from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app
from app.extensions import db
from app.models import User


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app("testing")
    app.config.update(
        SECRET_KEY="test-key",
        SQLALCHEMY_DATABASE_URI=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        UPLOAD_FOLDER=str(tmp_path / "uploads"),
    )

    with app.app_context():
        db.drop_all()
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_user(app):
    with app.app_context():
        user = User(email="admin@example.com")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        return user.email
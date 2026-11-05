from flask import current_app

from app.extensions import db
from app.models import User
from app.tenancy import get_current_tenant


def authenticate_user(email: str, password: str) -> User | None:
    user = User.query.filter_by(email=email.strip().lower()).first()
    if user is None or not user.is_active:
        return None
    if not user.check_password(password):
        return None
    return user


def load_tenant_user(user_id: str) -> User | None:
    tenant = get_current_tenant()
    if not isinstance(user_id, str):
        current_app.logger.info("Rejected invalid authentication identity.")
        return None
    slug, separator, local_id = user_id.partition(":")
    if not separator or slug != tenant.slug:
        current_app.logger.info("Rejected authentication identity outside the active tenant.")
        return None
    try:
        numeric_id = int(local_id)
    except ValueError:
        current_app.logger.info("Rejected invalid authentication user ID.")
        return None
    if not 0 < numeric_id <= 2**63 - 1:
        current_app.logger.info("Rejected out-of-range authentication user ID.")
        return None
    user = db.session.get(User, numeric_id)
    return user if user is not None and user.is_active else None
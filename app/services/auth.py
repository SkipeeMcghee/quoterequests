from app.models import User


def authenticate_user(email: str, password: str) -> User | None:
    user = User.query.filter_by(email=email.strip().lower()).first()
    if user is None or not user.is_active:
        return None
    if not user.check_password(password):
        return None
    return user
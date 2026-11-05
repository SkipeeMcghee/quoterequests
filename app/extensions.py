from typing import Any

from flask import g
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_sqlalchemy.session import Session
from flask_wtf import CSRFProtect
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import InvalidRequestError

from app.tenancy import get_current_tenant, get_registry


class TenantRoutingSession(Session):
    _tenant_slug: str | None = None

    def get_bind(
        self,
        mapper: Any = None,
        clause: Any = None,
        bind: Engine | Connection | None = None,
        **kwargs: Any,
    ) -> Engine | Connection:
        tenant = get_current_tenant()
        if self._tenant_slug is not None and self._tenant_slug != tenant.slug:
            raise InvalidRequestError("A session cannot switch tenants.")
        engine = get_registry().engine_for(tenant)
        if bind is not None and bind is not engine and not (
            isinstance(bind, Connection) and bind.engine is engine
        ):
            raise InvalidRequestError("An explicit bind cannot bypass tenant routing.")
        self._tenant_slug = tenant.slug
        return bind if bind is not None else engine

    def close(self) -> None:
        super().close()
        self._tenant_slug = None


db = SQLAlchemy(session_options={"class_": TenantRoutingSession})
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "admin.admin_entry"
login_manager.login_message_category = "warning"
csrf = CSRFProtect()


def teardown_tenant_request(error: BaseException | None) -> None:
    db.session.remove()
    g.pop("tenant", None)
    g.pop("_login_user", None)
from __future__ import annotations

from flask import current_app
from sqlalchemy import func
from werkzeug.exceptions import BadRequest, NotFound

from app.extensions import db
from app.models import ServiceOption


def is_services_enabled(config=None) -> bool:
    settings = config or current_app.config
    return bool(settings.get("ENABLE_SERVICES", False))


def require_services_enabled() -> None:
    if not is_services_enabled():
        raise NotFound()


def list_services(*, include_inactive: bool = True) -> list[ServiceOption]:
    if not is_services_enabled():
        return []
    return list(ServiceOption.ordered_query(include_inactive=include_inactive).all())


def list_active_services() -> list[ServiceOption]:
    return list_services(include_inactive=False)


def list_service_name_choices(*, include_inactive: bool = False) -> list[tuple[str, str]]:
    return [(service.name, service.name) for service in list_services(include_inactive=include_inactive)]


def list_service_id_choices(
    *,
    include_inactive: bool = False,
    selected_ids: list[int] | None = None,
) -> list[tuple[int, str]]:
    services = list_services(include_inactive=include_inactive)
    selected_lookup = {service_id for service_id in (selected_ids or []) if service_id is not None}
    if selected_lookup and not include_inactive:
        existing_ids = {service.id for service in services}
        missing_ids = selected_lookup - existing_ids
        if missing_ids:
            services.extend(
                ServiceOption.ordered_query(include_inactive=True)
                .filter(ServiceOption.id.in_(missing_ids))
                .all()
            )
            services.sort(key=lambda service: (service.display_order, service.name.lower(), service.id))

    return [(service.id, _format_service_label(service)) for service in services]


def resolve_service_options_by_ids(service_ids: list[int] | None) -> list[ServiceOption]:
    if not service_ids or not is_services_enabled():
        return []

    normalized_service_ids = list(dict.fromkeys(service_ids))
    service_options = list(
        ServiceOption.ordered_query(include_inactive=True)
        .filter(ServiceOption.id.in_(normalized_service_ids))
        .all()
    )
    service_lookup = {service.id: service for service in service_options}
    if len(service_lookup) != len(set(normalized_service_ids)):
        raise NotFound("One or more services were not found.")
    return [service_lookup[service_id] for service_id in normalized_service_ids]


def resolve_active_service_options_by_names(service_names: list[str] | None) -> list[ServiceOption]:
    if not service_names or not is_services_enabled():
        return []

    normalized_service_names = []
    for raw_name in service_names:
        cleaned_name = (raw_name or "").strip()
        if cleaned_name and cleaned_name not in normalized_service_names:
            normalized_service_names.append(cleaned_name)

    if not normalized_service_names:
        return []

    service_options = list(
        ServiceOption.ordered_query(include_inactive=False)
        .filter(ServiceOption.name.in_(normalized_service_names))
        .all()
    )
    service_lookup = {service.name: service for service in service_options}
    if len(service_lookup) != len(normalized_service_names):
        raise BadRequest("Choose one or more valid services.")
    return [service_lookup[service_name] for service_name in normalized_service_names]


def get_service_option(service_id: int) -> ServiceOption:
    require_services_enabled()
    service = db.session.get(ServiceOption, service_id)
    if service is None:
        raise NotFound("Service not found.")
    return service


def create_service_option(*, name: str, description: str | None = None, display_order: int = 0) -> ServiceOption:
    require_services_enabled()
    cleaned_name = _clean_service_name(name)
    _ensure_unique_service_name(cleaned_name)

    service = ServiceOption(
        name=cleaned_name,
        description=_clean_service_description(description),
        display_order=display_order,
        is_active=True,
    )
    db.session.add(service)
    db.session.commit()
    return service


def update_service_option(
    service_id: int,
    *,
    name: str,
    description: str | None = None,
    display_order: int = 0,
) -> ServiceOption:
    require_services_enabled()
    service = get_service_option(service_id)
    cleaned_name = _clean_service_name(name)
    _ensure_unique_service_name(cleaned_name, existing_service_id=service.id)

    service.name = cleaned_name
    service.description = _clean_service_description(description)
    service.display_order = display_order
    db.session.commit()
    return service


def set_service_option_active(service_id: int, *, is_active: bool) -> ServiceOption:
    require_services_enabled()
    service = get_service_option(service_id)
    service.is_active = is_active
    db.session.commit()
    return service


def _clean_service_name(raw_name: str | None) -> str:
    cleaned_name = (raw_name or "").strip()
    if not cleaned_name:
        raise BadRequest("Service name is required.")
    return cleaned_name


def _clean_service_description(raw_description: str | None) -> str | None:
    return (raw_description or "").strip() or None


def _ensure_unique_service_name(cleaned_name: str, existing_service_id: int | None = None) -> None:
    query = ServiceOption.query.filter(func.lower(ServiceOption.name) == cleaned_name.lower())
    if existing_service_id is not None:
        query = query.filter(ServiceOption.id != existing_service_id)
    if query.first() is not None:
        raise BadRequest("A service with that name already exists.")


def _format_service_label(service: ServiceOption) -> str:
    if service.is_active:
        return service.name
    return f"{service.name} (inactive)"
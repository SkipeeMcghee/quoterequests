from __future__ import annotations

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.forms.quote_request import QuoteRequestForm
from app.models import Appointment, QuoteRequest, ServiceOption
from app.services.email_hooks import send_admin_notification, send_customer_confirmation
from app.services.uploads import cleanup_request_photo_dir, save_request_photos


def create_quote_request(form: QuoteRequestForm, uploaded_files: list[FileStorage], request_type: str = "Quote request") -> QuoteRequest:
    if request_type not in QuoteRequest.REQUEST_TYPES:
        request_type = QuoteRequest.REQUEST_TYPES[0]

    payload, service_names = _quote_request_payload(form, request_type)
    quote_request = QuoteRequest(**payload)
    db.session.add(quote_request)

    try:
        db.session.flush()

        quote_request.services.extend(_resolve_service_options(service_names))
        for photo in save_request_photos(uploaded_files or [], quote_request.id):
            quote_request.photos.append(photo)

        additional_notes = (form.additional_notes.data or "").strip() or None
        if additional_notes:
            quote_request.additional_notes = additional_notes

        if current_app.config.get("ENABLE_SCHEDULING") and request_type == "Work request":
            preferred_date = form.preferred_date.data
            preferred_window = (form.preferred_time_window.data or "").strip() or None
            if preferred_date or preferred_window or additional_notes:
                appointment = Appointment(
                    quote_request=quote_request,
                    requested_date=preferred_date,
                    requested_time_window=preferred_window,
                    customer_notes=None,
                    internal_notes=additional_notes,
                    status="Requested",
                )
                db.session.add(appointment)
                quote_request.appointments.append(appointment)

        db.session.commit()
    except Exception:
        db.session.rollback()
        if quote_request.id is not None:
            cleanup_request_photo_dir(quote_request.id)
        raise

    _trigger_email_hooks(quote_request)
    return quote_request


def _quote_request_payload(form: QuoteRequestForm, request_type: str) -> tuple[dict[str, str | None], list[str]]:
    phone = (form.phone.data or "").strip() or None
    email = (form.email.data or "").strip().lower() or None

    service_names = [name.strip() for name in (form.services.data or []) if name and name.strip()]
    return (
        {
            "full_name": form.full_name.data.strip(),
            "phone": phone,
            "email": email,
            "city": form.city.data.strip(),
            "request_type": request_type,
            "additional_notes": (form.additional_notes.data or "").strip() or None,
        },
        list(dict.fromkeys(service_names)),
    )


def _resolve_service_options(service_names: list[str]) -> list[ServiceOption]:
    if not service_names:
        return []

    try:
        existing = {
            option.name: option
            for option in ServiceOption.query.filter(ServiceOption.name.in_(service_names)).all()
        }
    except SQLAlchemyError:
        db.session.rollback()
        db.create_all()
        existing = {
            option.name: option
            for option in ServiceOption.query.filter(ServiceOption.name.in_(service_names)).all()
        }

    resolved = []
    for name in service_names:
        option = existing.get(name)
        if option is None:
            option = ServiceOption(name=name)
            db.session.add(option)
            existing[name] = option
        resolved.append(option)
    return resolved


def _trigger_email_hooks(quote_request: QuoteRequest) -> None:
    for send_hook in (send_customer_confirmation, send_admin_notification):
        try:
            send_hook(quote_request)
        except Exception:
            current_app.logger.exception(
                "Email hook failed for quote request %s",
                quote_request.id,
            )
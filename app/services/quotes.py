from __future__ import annotations

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.forms.quote_request import QuoteRequestForm
from app.models import QuoteRequest
from app.services.email_hooks import send_admin_notification, send_customer_confirmation
from app.services.uploads import cleanup_request_photo_dir, save_request_photos


def create_quote_request(form: QuoteRequestForm, uploaded_files: list[FileStorage]) -> QuoteRequest:
    quote_request = QuoteRequest(**_quote_request_payload(form))
    db.session.add(quote_request)

    try:
        db.session.flush()

        for photo in save_request_photos(uploaded_files or [], quote_request.id):
            quote_request.photos.append(photo)

        db.session.commit()
    except Exception:
        db.session.rollback()
        if quote_request.id is not None:
            cleanup_request_photo_dir(quote_request.id)
        raise

    _trigger_email_hooks(quote_request)
    return quote_request


def _quote_request_payload(form: QuoteRequestForm) -> dict[str, str | None]:
    return {
        "full_name": form.full_name.data.strip(),
        "phone": form.phone.data.strip(),
        "email": form.email.data.strip().lower(),
        "service_type": form.service_type.data.strip(),
        "address": form.address.data.strip(),
        "description": form.description.data.strip(),
        "preferred_contact_method": form.preferred_contact_method.data,
        "preferred_contact_time": (form.preferred_contact_time.data or "").strip() or None,
    }


def _trigger_email_hooks(quote_request: QuoteRequest) -> None:
    for send_hook in (send_customer_confirmation, send_admin_notification):
        try:
            send_hook(quote_request)
        except Exception:
            current_app.logger.exception(
                "Email hook failed for quote request %s",
                quote_request.id,
            )
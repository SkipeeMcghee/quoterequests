from __future__ import annotations

from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.forms.quote_request import QuoteRequestForm
from app.models import QuoteRequest
from app.services.email_hooks import send_admin_notification, send_customer_confirmation
from app.services.uploads import save_request_photos


def create_quote_request(form: QuoteRequestForm, uploaded_files: list[FileStorage]) -> QuoteRequest:
    quote_request = QuoteRequest(
        full_name=form.full_name.data.strip(),
        phone=form.phone.data.strip(),
        email=form.email.data.strip().lower(),
        service_type=form.service_type.data.strip(),
        address=form.address.data.strip(),
        description=form.description.data.strip(),
        preferred_contact_method=form.preferred_contact_method.data,
        preferred_contact_time=(form.preferred_contact_time.data or "").strip() or None,
    )
    db.session.add(quote_request)
    db.session.flush()

    for photo in save_request_photos(uploaded_files or [], quote_request.id):
        quote_request.photos.append(photo)

    db.session.commit()

    send_customer_confirmation(quote_request)
    send_admin_notification(quote_request)
    return quote_request
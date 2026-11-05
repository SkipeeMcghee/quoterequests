"""Outbound notifications for a submitted request.

The transport lives in app.services.email; this module decides who gets what and
renders the text. Both senders are safe to call when email is switched off.
"""

from __future__ import annotations

from flask import current_app, has_request_context, render_template, url_for

from app.models import QuoteRequest
from app.services.email import send_email
from app.tenancy import tenant_config


def send_customer_confirmation(quote_request: QuoteRequest) -> bool:
    if not quote_request.email:
        current_app.logger.info(
            "No customer email on request %s; confirmation skipped", quote_request.id
        )
        return False

    body = render_template(
        "email/customer_confirmation.txt",
        quote_request=quote_request,
        business_name=tenant_config("BUSINESS_NAME", ""),
        phone=tenant_config("BUSINESS_PHONE", ""),
        email=tenant_config("BUSINESS_EMAIL", ""),
        service_area=tenant_config("SERVICE_AREA", ""),
    )
    return send_email(
        to=quote_request.email,
        subject=f"We received your request - {quote_request.request_number}",
        body=body,
    )


def send_admin_notification(quote_request: QuoteRequest) -> bool:
    recipient = (tenant_config("ADMIN_NOTIFICATION_EMAIL") or "").strip()
    if not recipient:
        current_app.logger.warning(
            "ADMIN_NOTIFICATION_EMAIL is not set; notification for request %s skipped",
            quote_request.id,
        )
        return False

    body = render_template(
        "email/admin_notification.txt",
        quote_request=quote_request,
        business_name=tenant_config("BUSINESS_NAME", ""),
        photo_count=len(quote_request.photos or []),
        request_url=_request_url(quote_request),
    )
    return send_email(
        to=recipient,
        subject=(
            f"New {quote_request.normalized_request_type.lower()} "
            f"#{quote_request.request_number} - {quote_request.full_name}"
        ),
        body=body,
    )


def _request_url(quote_request: QuoteRequest) -> str:
    origin = tenant_config("CANONICAL_ORIGIN", "")
    if not origin and has_request_context():
        return url_for("admin.request_detail", request_id=quote_request.id, _external=True)
    adapter = current_app.url_map.bind(
        "localhost", script_name=current_app.config.get("APPLICATION_ROOT", "/"),
    )
    path = adapter.build("admin.request_detail", {"request_id": quote_request.id})
    return f"{origin}{path}"

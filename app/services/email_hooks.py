from __future__ import annotations

from flask import current_app

from app.models import QuoteRequest


def send_customer_confirmation(quote_request: QuoteRequest) -> None:
    _log_email_hook(
        recipient=quote_request.email,
        subject=f"We received your request from {current_app.config['COMPANY_NAME']}",
        template="customer_confirmation",
        quote_request=quote_request,
    )


def send_admin_notification(quote_request: QuoteRequest) -> None:
    _log_email_hook(
        recipient=current_app.config["ADMIN_NOTIFICATION_EMAIL"],
        subject=f"New quote request: {quote_request.service_list_display}",
        template="admin_notification",
        quote_request=quote_request,
    )


def _log_email_hook(*, recipient: str, subject: str, template: str, quote_request: QuoteRequest) -> None:
    current_app.logger.info(
        "Email hook triggered",
        extra={
            "recipient": recipient,
            "subject": subject,
            "template": template,
            "quote_request_id": quote_request.id,
        },
    )
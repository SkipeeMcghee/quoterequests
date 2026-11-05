"""SMTP delivery for outbound notifications.

Disabled by default so a fresh install never tries to talk to a mail server. Turn it
on with EMAIL_ENABLED=true plus the SMTP settings; the defaults below match a Brevo
relay (smtp-relay.brevo.com:587, SMTP key as the password) but nothing is hard-wired
to it.

Sending never raises. A quote request must still be saved even when the mail server
is down or misconfigured, so failures are logged and reported as False.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from flask import current_app

from app.tenancy import current_tenant_settings


@dataclass(frozen=True)
class EmailSettings:
    enabled: bool
    host: str
    port: int
    username: str
    password: str
    use_starttls: bool
    use_ssl: bool
    timeout: int
    from_email: str
    from_name: str
    reply_to: str

    @property
    def is_deliverable(self) -> bool:
        return self.enabled and bool(self.host) and bool(self.from_email)


def load_settings(config=None) -> EmailSettings:
    config = current_tenant_settings() if config is None else config
    return EmailSettings(
        enabled=bool(config.get("EMAIL_ENABLED", False)),
        host=(config.get("SMTP_HOST") or "").strip(),
        port=int(config.get("SMTP_PORT") or 587),
        username=(config.get("SMTP_USERNAME") or "").strip(),
        password=config.get("SMTP_PASSWORD") or "",
        use_starttls=bool(config.get("SMTP_USE_TLS", True)),
        use_ssl=bool(config.get("SMTP_USE_SSL", False)),
        timeout=int(config.get("SMTP_TIMEOUT") or 10),
        from_email=(config.get("DEFAULT_FROM_EMAIL") or "").strip(),
        from_name=(config.get("EMAIL_FROM_NAME") or config.get("BUSINESS_NAME") or "").strip(),
        reply_to=(config.get("EMAIL_REPLY_TO") or "").strip(),
    )


def is_configured() -> bool:
    return load_settings().is_deliverable


def build_message(settings: EmailSettings, *, to: str, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = f"{settings.from_name} <{settings.from_email}>" if settings.from_name else settings.from_email
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    if settings.reply_to:
        message["Reply-To"] = settings.reply_to
    message.set_content(body)
    return message


def send_email(*, to: str, subject: str, body: str) -> bool:
    """Send one plain-text email. Returns True only if the server accepted it."""

    settings = load_settings()

    if not settings.enabled:
        current_app.logger.info(
            "Email disabled; skipped send", extra={"recipient": to, "subject": subject}
        )
        return False

    if not settings.is_deliverable:
        current_app.logger.error(
            "Email enabled but incompletely configured; skipped send",
            extra={
                "missing_host": not settings.host,
                "missing_from": not settings.from_email,
                "recipient": to,
            },
        )
        return False

    recipient = (to or "").strip()
    if not recipient:
        current_app.logger.warning("Email skipped: no recipient", extra={"subject": subject})
        return False

    message = build_message(settings, to=recipient, subject=subject, body=body)

    try:
        if settings.use_ssl:
            with smtplib.SMTP_SSL(
                settings.host,
                settings.port,
                timeout=settings.timeout,
                context=ssl.create_default_context(),
            ) as server:
                _deliver(server, settings, message)
        else:
            with smtplib.SMTP(settings.host, settings.port, timeout=settings.timeout) as server:
                if settings.use_starttls:
                    server.starttls(context=ssl.create_default_context())
                _deliver(server, settings, message)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        current_app.logger.error(
            "Email send failed: %s",
            exc,
            extra={"recipient": recipient, "subject": subject, "smtp_host": settings.host},
        )
        return False

    current_app.logger.info(
        "Email sent", extra={"recipient": recipient, "subject": subject}
    )
    return True


def _deliver(server: smtplib.SMTP, settings: EmailSettings, message: EmailMessage) -> None:
    if settings.username:
        server.login(settings.username, settings.password)
    server.send_message(message)

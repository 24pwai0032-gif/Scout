"""Email delivery via the official SendGrid SDK (direct, not MCP)."""

from __future__ import annotations

from scout.config import get_settings
from scout.logging_config import get_logger

log = get_logger("scout.notifications.email")


def send_email(subject: str, body: str) -> bool:
    settings = get_settings()
    if not settings.email_enabled:
        log.info("email_disabled")
        return False
    if not (settings.sendgrid_api_key and settings.email_from and settings.email_to):
        log.warning("email_enabled_but_unconfigured")
        return False
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=settings.email_from,
            to_emails=settings.email_to,
            subject=f"[Scout] {subject}",
            plain_text_content=body,
        )
        SendGridAPIClient(settings.sendgrid_api_key).send(message)
        log.info("email_sent", to=settings.email_to)
        return True
    except Exception as exc:
        log.warning("email_send_failed", error=str(exc))
        return False

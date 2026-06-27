"""Slack delivery via the official slack_sdk (direct, not MCP)."""

from __future__ import annotations

from scout.config import get_settings
from scout.logging_config import get_logger

log = get_logger("scout.notifications.slack")


def send_slack(text: str) -> bool:
    settings = get_settings()
    if not settings.slack_enabled:
        log.info("slack_disabled")
        return False
    if not settings.slack_bot_token:
        log.warning("slack_enabled_but_no_token")
        return False
    try:
        from slack_sdk import WebClient

        client = WebClient(token=settings.slack_bot_token)
        client.chat_postMessage(channel=settings.slack_channel, text=text, mrkdwn=True)
        log.info("slack_sent", channel=settings.slack_channel)
        return True
    except Exception as exc:
        log.warning("slack_send_failed", error=str(exc))
        return False

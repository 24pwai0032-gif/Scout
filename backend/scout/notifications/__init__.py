"""Phase 5 — notifications via direct Slack + SendGrid SDK calls (no MCP wrappers in v1).

`dispatch(finding)` is called after a Finding is persisted. Each channel is independently
enabled/configured via env and fails soft (logged), never crashing the pipeline.
"""

from __future__ import annotations

from scout.logging_config import get_logger
from scout.models import Finding
from scout.notifications.email import send_email
from scout.notifications.slack import send_slack

log = get_logger("scout.notifications")


def format_finding(finding: Finding) -> str:
    lines = [
        f"*Scout finding — {finding.store_id}*",
        finding.headline,
        f"\n*Recommended action:* {finding.recommended_action}",
        f"_confidence {finding.confidence} · cause "
        f"{finding.confirmed_cause.value if finding.confirmed_cause else 'inconclusive'}_",
    ]
    if finding.evidence:
        lines.append("\n*Evidence:*")
        for e in finding.evidence[:6]:
            mark = {True: "✓", False: "✗", None: "·"}[e.supports]
            lines.append(f"  {mark} {e.result_summary}")
    return "\n".join(lines)


def dispatch(finding: Finding) -> None:
    text = format_finding(finding)
    send_slack(text)
    send_email(subject=finding.headline, body=text)

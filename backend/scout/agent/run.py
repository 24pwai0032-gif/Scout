"""Local runner: detect anomalies on the (demo or real) store and investigate the
strongest one, printing the Finding. The on-ramp to the whole agentic loop.

    python -m scout.agent.run
"""

from __future__ import annotations

import sys

from scout.agent.detection import detect_recent
from scout.agent.graph import run_investigation
from scout.agent.llm import make_llm
from scout.agent.mcp_client import make_tools
from scout.config import get_settings
from scout.logging_config import configure_logging, get_logger
from scout.models import AnomalyEvent

log = get_logger("scout.agent.run")


def investigate_strongest(metric: str = "revenue") -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    anomalies = detect_recent(settings.store_id, metric, lookback_days=14, settings=settings)
    if not anomalies:
        print("No anomalies in the recent window. (Seed the demo: python -m scout.capture.seed_demo)")
        return
    anomaly: AnomalyEvent = max(anomalies, key=lambda a: a.score)

    tools = make_tools(settings)
    llm = make_llm(settings)
    try:
        finding = run_investigation(anomaly, tools, llm, settings)
    finally:
        try:
            tools.close()
        except Exception as exc:  # teardown must never lose the finding
            log.warning("tools_close_error", error=str(exc))

    print("\n" + "=" * 78)
    print("SCOUT FINDING")
    print("=" * 78)
    print(f"  {finding.headline}")
    print(f"\n  Action: {finding.recommended_action}")
    print(
        f"\n  confirmed_cause={finding.confirmed_cause.value if finding.confirmed_cause else None}"
        f"  confidence={finding.confidence}  llm={finding.llm_mode}"
        f"  inconclusive={finding.inconclusive}"
    )
    print(f"  like-for-like: {anomaly.like_for_like()}  (z={anomaly.robust_z})")
    print("\n  Evidence:")
    for e in finding.evidence:
        mark = {True: "+", False: "-", None: "?"}[e.supports]
        print(f"    [{mark}] {e.tool}: {e.result_summary}")
    print("=" * 78)


if __name__ == "__main__":
    investigate_strongest(sys.argv[1] if len(sys.argv) > 1 else "revenue")

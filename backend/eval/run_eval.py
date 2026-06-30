"""Deterministic eval: detection precision/recall + cause-attribution rate over the
golden cases, using a recorded cassette for the agent so it replays offline.

    python -m eval.run_eval        (or: make eval)

Exits non-zero if any metric misses its gate — this is how every change to detection
thresholds or hypotheses is judged.
"""

from __future__ import annotations

import os
import sys
from datetime import date

from eval.cassettes import CassetteTools, RecordingTools
from eval.golden_cases import golden_cases
from scout.agent.detection import detect_for_day
from scout.agent.graph import run_investigation
from scout.agent.llm import StubLLM
from scout.capture.seed_demo import seed
from scout.config import get_settings
from scout.logging_config import configure_logging, get_logger
from scout.mcp_server.data_source import make_data_source

log = get_logger("scout.eval")


class _InProcess:
    """Direct data-source tools for recording (no MCP subprocess in the eval)."""

    def __init__(self, settings):
        self._s = make_data_source(settings)

    def __getattr__(self, item):
        return getattr(self._s, item)

    def close(self):
        pass


def main() -> int:
    # The eval is a deterministic OFFLINE harness — pin it independent of any local .env
    # (which may point at a live Shopify store / real LLM).
    os.environ["SCOUT_DATA_SOURCE"] = "demo"
    os.environ["SCOUT_LLM_MODE"] = "stub"
    os.environ["SCOUT_STORE_ID"] = "demo-store"
    os.environ["SCOUT_MCP_TRANSPORT"] = "inprocess"
    get_settings.cache_clear()

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    seed(settings.store_id)  # deterministic fixture source
    cases = golden_cases()

    # ── Detection metrics ────────────────────────────────────────────────────
    tp = fp = tn = fn = 0
    for c in cases:
        anomaly = detect_for_day(settings.store_id, "revenue", c.day, settings)
        flagged = anomaly is not None
        if c.expect_flag and flagged:
            tp += 1
        elif c.expect_flag and not flagged:
            fn += 1
        elif not c.expect_flag and flagged:
            fp += 1
        else:
            tn += 1
        print(f"  detection  {c.name:18} {c.day}  expect_flag={c.expect_flag!s:5}  flagged={flagged!s:5}  "
              f"{'OK' if c.expect_flag == flagged else 'MISS'}")

    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    fp_rate = fp / (fp + tn) if (fp + tn) else 0.0

    # ── Attribution via recorded cassette (offline replay) ───────────────────
    incident = next(c for c in cases if c.expect_flag)
    anomaly = detect_for_day(settings.store_id, "revenue", incident.day, settings)
    assert anomaly is not None, "incident day must flag for the attribution eval"

    rec = RecordingTools(_InProcess(settings))
    run_investigation(anomaly, rec, StubLLM(settings), settings)
    rec.save("incident")  # cassette written

    cassette = CassetteTools("incident")
    finding = run_investigation(anomaly, cassette, StubLLM(settings), settings)
    got = finding.confirmed_cause.value if finding.confirmed_cause else None
    attribution_ok = got == incident.expect_cause
    print(f"  attribution {incident.name:18} expect={incident.expect_cause}  got={got}  "
          f"{'OK' if attribution_ok else 'MISS'}  (replayed from cassette)")
    attribution_rate = 1.0 if attribution_ok else 0.0

    # ── Report + gate ────────────────────────────────────────────────────────
    print("\n  ── eval summary ──")
    print(f"  precision={precision:.2f}  recall={recall:.2f}  false_positive_rate={fp_rate:.2f}  "
          f"attribution_rate={attribution_rate:.2f}")
    print(f"  TP={tp} FP={fp} TN={tn} FN={fn}")

    gates = {
        "precision>=1.0": precision >= 1.0,
        "recall>=1.0": recall >= 1.0,
        "false_positive_rate<=0.0": fp_rate <= 0.0,
        "attribution_rate>=1.0": attribution_rate >= 1.0,
    }
    failed = [k for k, ok in gates.items() if not ok]
    if failed:
        print(f"\n  EVAL FAILED gates: {failed}")
        return 1
    print("\n  EVAL PASSED ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())

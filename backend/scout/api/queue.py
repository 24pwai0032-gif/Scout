"""Debounced investigation queue + background worker.

Investigation runs NEVER happen synchronously inside a webhook handler. An active store
fires order webhooks constantly, so triggers are coalesced to at most one run per store
per `debounce_minutes`. Manual /scout/run can `force` past the debounce.
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from queue import Empty, Queue
from uuid import uuid4

from scout.agent.detection import detect_recent
from scout.agent.graph import run_investigation
from scout.agent.llm import make_llm
from scout.agent.mcp_client import make_tools
from scout.api.persistence import save_finding, save_run
from scout.capture.schema import InvestigationRun
from scout.config import get_settings
from scout.logging_config import get_logger
from scout.timeutil import utcnow

log = get_logger("scout.api.queue")


def run_pipeline(store_id: str, trigger: str = "manual") -> int | None:
    """Detect the strongest recent anomaly, investigate it, persist + notify. Records an
    InvestigationRun audit row regardless of outcome. Returns the finding id, or None."""
    settings = get_settings()
    run_id = uuid4().hex[:8]
    started = utcnow()
    t0 = time.perf_counter()
    status, outcome, fid = "completed", "", None
    try:
        anomalies = detect_recent(store_id, "revenue", lookback_days=14, settings=settings)
        if not anomalies:
            outcome = "No anomaly (weekdays within baseline)"
            log.info("pipeline_no_anomaly", store_id=store_id)
        else:
            anomaly = max(anomalies, key=lambda a: a.score)
            tools = make_tools(settings)
            try:
                finding = run_investigation(anomaly, tools, make_llm(settings), settings)
            finally:
                try:
                    tools.close()
                except Exception as exc:
                    log.warning("tools_close_error", error=str(exc))
            fid = save_finding(finding)
            cause = finding.confirmed_cause.value if finding.confirmed_cause else None
            status = "inconclusive" if finding.inconclusive else "completed"
            outcome = f"{cause} — {finding.headline[:64]}" if cause else "No cause confirmed"
            log.info("pipeline_finding_saved", store_id=store_id, finding_id=fid)
            try:
                from scout.notifications import dispatch

                dispatch(finding)
            except Exception as exc:  # notifications must never crash the pipeline
                log.warning("notify_error", error=str(exc))
    except Exception as exc:
        status, outcome = "failed", str(exc)[:120]
        log.error("pipeline_error", store_id=store_id, error=str(exc))
    finally:
        try:
            save_run(
                InvestigationRun(
                    id=run_id, store_id=store_id, trigger=trigger, status=status,
                    outcome=outcome, duration_ms=int((time.perf_counter() - t0) * 1000),
                    finding_id=fid, started_at=started,
                )
            )
        except Exception as exc:
            log.warning("run_record_error", error=str(exc))
    return fid


class InvestigationQueue:
    def __init__(self):
        self._q: Queue = Queue()
        self._last_run: dict[str, datetime] = {}
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, name="scout-worker", daemon=True)
        self._worker.start()
        log.info("queue_worker_started")

    def stop(self) -> None:
        self._stop.set()

    def enqueue(self, store_id: str, reason: str = "manual", force: bool = False) -> bool:
        """Returns True if queued, False if debounced/coalesced."""
        settings = get_settings()
        last = self._last_run.get(store_id)
        if not force and last and utcnow() - last < timedelta(minutes=settings.debounce_minutes):
            log.info("debounced", store_id=store_id, reason=reason)
            return False
        # Reserve the window now so a burst of webhooks coalesces to one run.
        self._last_run[store_id] = utcnow()
        self._q.put((store_id, reason))
        log.info("enqueued", store_id=store_id, reason=reason)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                store_id, reason = self._q.get(timeout=0.5)
            except Empty:
                continue
            try:
                run_pipeline(store_id, trigger=_trigger_from_reason(reason))
            except Exception as exc:
                log.error("pipeline_error", store_id=store_id, error=str(exc))
            finally:
                self._q.task_done()


def _trigger_from_reason(reason: str) -> str:
    if reason.startswith("webhook"):
        return "webhook"
    if reason in ("schedule", "backfill"):
        return "schedule"
    return "manual"


_QUEUE: InvestigationQueue | None = None


def get_queue() -> InvestigationQueue:
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = InvestigationQueue()
    return _QUEUE

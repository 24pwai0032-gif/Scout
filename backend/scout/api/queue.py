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

from scout.agent.detection import detect_recent
from scout.agent.graph import run_investigation
from scout.agent.llm import make_llm
from scout.agent.mcp_client import make_tools
from scout.api.persistence import save_finding
from scout.config import get_settings
from scout.logging_config import get_logger
from scout.timeutil import utcnow

log = get_logger("scout.api.queue")


def run_pipeline(store_id: str) -> int | None:
    """Detect the strongest recent anomaly, investigate it, persist + notify. Returns
    the finding id, or None if nothing to report."""
    settings = get_settings()
    anomalies = detect_recent(store_id, "revenue", lookback_days=14, settings=settings)
    if not anomalies:
        log.info("pipeline_no_anomaly", store_id=store_id)
        return None
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
    log.info("pipeline_finding_saved", store_id=store_id, finding_id=fid)
    try:
        from scout.notifications import dispatch

        dispatch(finding)
    except Exception as exc:  # notifications must never crash the pipeline
        log.warning("notify_error", error=str(exc))
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
                run_pipeline(store_id)
            except Exception as exc:
                log.error("pipeline_error", store_id=store_id, error=str(exc))
            finally:
                self._q.task_done()


_QUEUE: InvestigationQueue | None = None


def get_queue() -> InvestigationQueue:
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = InvestigationQueue()
    return _QUEUE

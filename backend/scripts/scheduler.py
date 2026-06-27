"""Scheduled backfill worker — rolls captured orders into the daily metric_timeseries so
same-weekday baselines stay current. Run as its own process/container.

    python scripts/scheduler.py            # default: every 3600s
    SCOUT_BACKFILL_INTERVAL=900 python scripts/scheduler.py
"""

from __future__ import annotations

import os
import time

from scout.capture.backfill import run_backfill
from scout.capture.db import init_db
from scout.config import get_settings
from scout.logging_config import configure_logging, get_logger

log = get_logger("scout.scheduler")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    init_db()
    interval = int(os.environ.get("SCOUT_BACKFILL_INTERVAL", "3600"))
    log.info("scheduler_started", interval_s=interval, store_id=settings.store_id)
    while True:
        try:
            run_backfill(settings.store_id)
        except Exception as exc:
            log.error("backfill_error", error=str(exc))
        time.sleep(interval)


if __name__ == "__main__":
    main()

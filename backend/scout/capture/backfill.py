"""Scheduled backfill: roll captured orders up into the daily metric_timeseries so the
same-weekday baselines exist as soon as possible.

Run on a schedule (cron / APScheduler / the compose 'worker'). Idempotent upsert per day.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select

from scout.capture.db import session_scope
from scout.capture.schema import MetricTimeseries, OrderSnapshot
from scout.logging_config import get_logger

log = get_logger("scout.capture.backfill")


def _upsert_metric(session, store_id: str, metric: str, day: date, value: float) -> None:
    row = session.execute(
        select(MetricTimeseries).where(
            MetricTimeseries.store_id == store_id,
            MetricTimeseries.metric == metric,
            MetricTimeseries.day == day,
        )
    ).scalar_one_or_none()
    if row:
        row.value = value
    else:
        session.add(
            MetricTimeseries(
                store_id=store_id,
                metric=metric,
                day=day,
                weekday=day.weekday(),
                value=value,
            )
        )


def rebuild_revenue_timeseries(store_id: str) -> int:
    """Aggregate captured orders into daily revenue rows. Returns #days written."""
    by_day: dict[date, float] = defaultdict(float)
    with session_scope() as s:
        orders = s.execute(
            select(OrderSnapshot).where(OrderSnapshot.store_id == store_id)
        ).scalars()
        for o in orders:
            by_day[o.created_at_store.date()] += o.total_price
        for day, total in by_day.items():
            _upsert_metric(s, store_id, "revenue", day, round(total, 2))
    log.info("revenue_timeseries_rebuilt", store_id=store_id, days=len(by_day))
    return len(by_day)


def run_backfill(store_id: str) -> None:
    rebuild_revenue_timeseries(store_id)

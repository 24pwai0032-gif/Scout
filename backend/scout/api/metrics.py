"""Metric series for the dashboard (served over HTTP so the UI imports no agent code)."""

from __future__ import annotations

import statistics

from sqlalchemy import select

from scout.capture.db import session_scope
from scout.capture.schema import MetricTimeseries
from scout.config import get_settings
from scout.mcp_server.data_source import make_data_source


def revenue_series(store_id: str, same_weekdays: int = 5) -> dict:
    """Daily revenue + a same-weekday robust baseline overlay (median of prior N)."""
    with session_scope() as s:
        rows = s.execute(
            select(MetricTimeseries.day, MetricTimeseries.value, MetricTimeseries.weekday)
            .where(MetricTimeseries.store_id == store_id, MetricTimeseries.metric == "revenue")
            .order_by(MetricTimeseries.day.asc())
        ).all()
    series = [{"date": str(d), "value": float(v), "weekday": int(wd)} for d, v, wd in rows]
    baseline = []
    for i, point in enumerate(series):
        priors = [p["value"] for p in series[:i] if p["weekday"] == point["weekday"]][-same_weekdays:]
        baseline.append({"date": point["date"], "baseline": statistics.median(priors) if priors else None})
    return {"series": series, "baseline": baseline}


def inventory_levels(store_id: str) -> list[dict]:
    settings = get_settings()
    return make_data_source(settings).get_inventory_levels()

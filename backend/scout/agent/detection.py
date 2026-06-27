"""Deterministic detection engine (pre-LLM). Turns the captured metric_timeseries into
AnomalyEvent objects using a day-of-week-aware, robust baseline.

DESIGN CHOICES (and why):
  * Same-weekday baseline (N=5): a Tuesday is compared ONLY against the last 5 Tuesdays.
    Comparing against a flat trailing mean that mixes weekends produces garbage, because
    weekday revenue genuinely differs by day-of-week. 5 weeks balances responsiveness
    against having enough points for a stable robust estimate.
  * Median + MAD (robust), NOT mean + std: one prior promo spike must not poison the
    baseline. MAD is scaled by 1.4826 so the robust z is comparable to a standard z for
    roughly-normal data.
  * Threshold robust_z >= 3.5: deliberately conservative to keep false positives low on a
    webhook-triggered LLM agent that costs money per run. Tunable via env + the eval
    harness against real findings.
  * Minimum history (3 same-weekdays): with fewer points we EMIT NOTHING and log why,
    rather than guessing — per the brief.
  * MAD ~ 0 guard: if the prior same-weekdays are near-identical, a robust z explodes on
    trivial noise. In that case we additionally require a meaningful relative move
    (>= 8%) before flagging.
"""

from __future__ import annotations

import statistics
from datetime import date

from sqlalchemy import select

from scout.capture.db import session_scope
from scout.capture.schema import MetricTimeseries
from scout.config import Settings, get_settings
from scout.logging_config import get_logger
from scout.models import AnomalyEvent

log = get_logger("scout.detection")

_MAD_SCALE = 1.4826
_MAD_EPS = 1e-6
_MIN_REL_MOVE_WHEN_FLAT = 0.08  # 8%
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _same_weekday_series(store_id: str, metric: str, target: date) -> list[tuple[date, float]]:
    """All prior rows for the SAME weekday as `target`, newest first, excluding target."""
    with session_scope() as s:
        rows = s.execute(
            select(MetricTimeseries.day, MetricTimeseries.value)
            .where(
                MetricTimeseries.store_id == store_id,
                MetricTimeseries.metric == metric,
                MetricTimeseries.weekday == target.weekday(),
                MetricTimeseries.day < target,
            )
            .order_by(MetricTimeseries.day.desc())
        ).all()
    return [(d, float(v)) for d, v in rows]


def _observed(store_id: str, metric: str, target: date) -> float | None:
    with session_scope() as s:
        val = s.execute(
            select(MetricTimeseries.value).where(
                MetricTimeseries.store_id == store_id,
                MetricTimeseries.metric == metric,
                MetricTimeseries.day == target,
            )
        ).scalar_one_or_none()
    return float(val) if val is not None else None


def detect_for_day(
    store_id: str, metric: str, target: date, settings: Settings | None = None
) -> AnomalyEvent | None:
    settings = settings or get_settings()
    observed = _observed(store_id, metric, target)
    if observed is None:
        log.info("no_observation", store_id=store_id, metric=metric, day=str(target))
        return None

    series = _same_weekday_series(store_id, metric, target)[: settings.baseline_same_weekdays]
    if len(series) < settings.min_baseline_history:
        log.info(
            "insufficient_history",
            store_id=store_id,
            metric=metric,
            day=str(target),
            have=len(series),
            need=settings.min_baseline_history,
        )
        return None

    values = [v for _, v in series]
    median = statistics.median(values)
    mad = statistics.median([abs(v - median) for v in values])
    deviation_pct = (observed - median) / median * 100 if median else 0.0

    if mad <= _MAD_EPS:
        # Baseline essentially flat: fall back to a relative-move gate.
        flagged = abs(deviation_pct) >= _MIN_REL_MOVE_WHEN_FLAT * 100
        robust_z = float("inf") if flagged else 0.0
    else:
        robust_z = (observed - median) / (_MAD_SCALE * mad)
        flagged = abs(robust_z) >= settings.robust_z_threshold

    weekday = _WEEKDAY_NAMES[target.weekday()]
    if not flagged:
        log.info(
            "no_anomaly",
            store_id=store_id,
            metric=metric,
            day=str(target),
            deviation_pct=round(deviation_pct, 1),
            robust_z=None if robust_z == float("inf") else round(robust_z, 2),
        )
        return None

    anomaly = AnomalyEvent(
        store_id=store_id,
        metric=metric,
        observed_value=round(observed, 2),
        baseline=round(median, 2),
        deviation_pct=round(deviation_pct, 1),
        robust_z=round(robust_z, 2) if robust_z != float("inf") else 999.0,
        weekday=weekday,
        comparison_window=[str(d) for d, _ in series],
        score=abs(round(robust_z, 2)) if robust_z != float("inf") else 999.0,
        date=str(target),
    )
    log.info(
        "anomaly_flagged",
        store_id=store_id,
        metric=metric,
        day=str(target),
        deviation_pct=anomaly.deviation_pct,
        robust_z=anomaly.robust_z,
    )
    return anomaly


def detect_recent(
    store_id: str, metric: str = "revenue", lookback_days: int = 14, settings: Settings | None = None
) -> list[AnomalyEvent]:
    """Scan the most recent `lookback_days` of the metric and return all anomalies."""
    settings = settings or get_settings()
    with session_scope() as s:
        days = s.execute(
            select(MetricTimeseries.day)
            .where(MetricTimeseries.store_id == store_id, MetricTimeseries.metric == metric)
            .order_by(MetricTimeseries.day.desc())
            .limit(lookback_days)
        ).scalars().all()
    out = []
    for d in days:
        a = detect_for_day(store_id, metric, d, settings)
        if a:
            out.append(a)
    return out

"""Phase 0.5 deliverable — verify captured events are landing in the DB.

    python scripts/verify_events.py
"""

from __future__ import annotations

from sqlalchemy import func, select

from scout.capture.db import init_db, session_scope
from scout.capture.schema import (
    InventoryLevelEvent,
    MetricTimeseries,
    OrderLineItem,
    OrderSnapshot,
)
from scout.config import get_settings


def main() -> None:
    init_db()
    store_id = get_settings().store_id
    with session_scope() as s:
        def count(model):
            return s.execute(
                select(func.count()).select_from(model).where(model.store_id == store_id)
            ).scalar_one()

        print(f"store_id = {store_id}")
        print(f"  order_snapshots:        {count(OrderSnapshot)}")
        print(f"  order_line_items:       {count(OrderLineItem)}")
        print(f"  inventory_level_events: {count(InventoryLevelEvent)}")
        print(f"  metric_timeseries:      {count(MetricTimeseries)}")
        latest = s.execute(
            select(MetricTimeseries.day, MetricTimeseries.value)
            .where(MetricTimeseries.store_id == store_id, MetricTimeseries.metric == "revenue")
            .order_by(MetricTimeseries.day.desc()).limit(5)
        ).all()
        print("  latest revenue days:", [(str(d), v) for d, v in latest])


if __name__ == "__main__":
    main()

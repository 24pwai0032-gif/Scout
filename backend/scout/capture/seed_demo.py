"""Deterministic DEMO data generator (EXPLICIT, not a silent fallback).

Seeds the local event store with ~8 weeks of synthetic orders, a weekday revenue
pattern, and a flagship incident: on the most recent past Tuesday the top SKU
(Black Tee) sells out at ~14:00, dropping revenue ~18% vs the prior Tuesdays, while
Grey Tee is ~3 days from its own stockout. Running detection + agent over this data
reproduces the brief's example finding — with NO Shopify/OpenAI needed.

Re-runnable: wipes the demo store's rows first.

    python -m scout.capture.seed_demo
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete

from scout.capture.backfill import rebuild_revenue_timeseries
from scout.capture.db import init_db, session_scope
from scout.capture.schema import (
    InventoryLevelEvent,
    OrderLineItem,
    OrderSnapshot,
    Store,
)
from scout.config import get_settings
from scout.logging_config import configure_logging, get_logger

log = get_logger("scout.capture.seed_demo")


@dataclass(frozen=True)
class Product:
    sku: str
    title: str
    price: float
    fraction: float  # share of a normal day's revenue
    current_stock: int


PRODUCTS = [
    Product("TEE-BLK-M", "Black Tee — M", 25.0, 0.35, current_stock=0),   # the top SKU
    Product("TEE-GRY-M", "Grey Tee — M", 25.0, 0.12, current_stock=10),   # ~3 days out
    Product("HOOD-BLK-L", "Black Hoodie — L", 60.0, 0.25, current_stock=40),
    Product("CAP-RED", "Red Cap", 20.0, 0.13, current_stock=60),
    Product("SOCK-3PK", "Socks 3-pack", 12.0, 0.15, current_stock=80),
]
TOP_SKU = "TEE-BLK-M"

# Base revenue by weekday (0=Mon..6=Sun); weekends differ — that's why detection must be
# day-of-week aware.
WEEKDAY_REVENUE = {0: 900, 1: 1000, 2: 950, 3: 1000, 4: 1200, 5: 700, 6: 600}

LOOKBACK_DAYS = 56  # 8 weeks → 8 prior same-weekdays available


def _sock_jitter(d: date) -> int:
    """Deterministic per-day jitter of -3..+3 SOCK units. This is the ONLY source of
    same-weekday variance, so the baseline MAD is small but non-zero (a few %) — enough
    to exercise the robust-z path without masking the ~18% incident.

    NOTE: an LCG-style mix (not `ordinal % 7`) so that same-weekday days — which share
    `ordinal mod 7` — get DIFFERENT jitter week to week (otherwise MAD collapses to 0)."""
    return ((d.toordinal() * 1103515245 + 12345) // 65536) % 7 - 3


def _orders_for_day(day, target, products, top_sku, weekday_revenue, jitter_sku):
    """Yield (timestamp, sku, title, qty, price) line-item tuples for a day."""
    wd = day.weekday()
    total = weekday_revenue[wd]  # fixed per weekday; variance comes from jitter SKU only
    is_target = day == target

    for p in products:
        units = max(0, round(total * p.fraction / p.price)) if p.price else 0
        if p.sku == jitter_sku:
            units = max(0, units + _sock_jitter(day))
        start_h, end_h = 9, 21
        if is_target and p.sku == top_sku:
            # Flagship incident: only sells until it goes out of stock at ~14:00.
            units = max(1, round(units / 2))  # roughly half a normal day → concentrates the gap
            start_h, end_h = 9, 13  # all sales before the 14:00 stockout
        if units == 0:
            continue
        # Bundle ~2 units per order; spread orders across business hours.
        n_orders = max(1, round(units / 2))
        span_min = (end_h - start_h) * 60
        remaining = units
        for i in range(n_orders):
            qty = 2 if remaining >= 2 and i < n_orders - 1 else remaining
            remaining -= qty
            if qty <= 0:
                continue
            minute = start_h * 60 + int(span_min * (i + 0.5) / n_orders)
            ts = datetime.combine(day, time(minute // 60, minute % 60))
            yield ts, p.sku, p.title, qty, p.price


def _inventory_events(target, products, top_sku):
    """Current levels for all SKUs + a declining series for the top SKU on the target
    day that crosses zero at 14:00 (the 'out of stock at 2pm' signal)."""
    events = []
    for hh, avail in [(9, 22), (11, 14), (12, 7), (14, 0)]:
        events.append((top_sku, datetime.combine(target, time(hh, 0)), avail))
    snapshot_at = datetime.combine(target, time(23, 0))
    for p in products:
        if p.sku == top_sku:
            continue  # its latest (0 @ 14:00) already stands as current
        events.append((p.sku, snapshot_at, p.current_stock))
    return events


def seed_history(
    store_id: str,
    products: list[Product],
    top_sku: str,
    weekday_revenue: dict | None = None,
    jitter_sku: str | None = None,
    domain: str = "demo.myshopify.com",
) -> dict:
    """Core generator: writes ~8 weeks of backdated orders + inventory events + the
    daily metric series for the given product set. Reused by the demo seeder and the
    live-catalog seeder (scripts/seed_live_history.py)."""
    weekday_revenue = weekday_revenue or WEEKDAY_REVENUE
    jitter_sku = jitter_sku or (products[-1].sku if products else "")
    today = date.today()
    offset = (today.weekday() - 1) % 7 or 7  # most recent past Tuesday = incident day
    target = today - timedelta(days=offset)
    start = target - timedelta(days=LOOKBACK_DAYS)

    init_db()
    with session_scope() as s:
        for model in (OrderLineItem, OrderSnapshot, InventoryLevelEvent):
            s.execute(delete(model).where(model.store_id == store_id))
        s.merge(Store(store_id=store_id, domain=domain, timezone="UTC"))

        order_seq = 0
        day = start
        while day <= target:
            for ts, sku, title, qty, price in _orders_for_day(
                day, target, products, top_sku, weekday_revenue, jitter_sku
            ):
                order_seq += 1
                ref = f"#D{order_seq:05d}"
                s.add(
                    OrderSnapshot(
                        store_id=store_id,
                        order_ref=ref,
                        created_at_store=ts,
                        total_price=round(qty * price, 2),
                        currency="USD",
                        financial_status="paid",
                    )
                )
                s.add(
                    OrderLineItem(
                        store_id=store_id,
                        order_ref=ref,
                        sku=sku,
                        title=title,
                        quantity=qty,
                        price=price,
                        created_at_store=ts,
                    )
                )
            day += timedelta(days=1)

        for sku, ts, avail in _inventory_events(target, products, top_sku):
            s.add(
                InventoryLevelEvent(
                    store_id=store_id,
                    sku=sku,
                    variant_id=f"var-{sku}",
                    location_id="loc-1",
                    available=avail,
                    occurred_at=ts,
                )
            )

    days = rebuild_revenue_timeseries(store_id)
    log.info("history_seeded", store_id=store_id, incident_day=str(target), metric_days=days)
    return {"store_id": store_id, "incident_day": str(target), "orders": order_seq}


def seed(store_id: str | None = None) -> dict:
    """Seed the synthetic DEMO store (fixed catalog)."""
    store_id = store_id or get_settings().store_id
    return seed_history(store_id, PRODUCTS, TOP_SKU, WEEKDAY_REVENUE, jitter_sku="SOCK-3PK")


if __name__ == "__main__":
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    result = seed()
    print(
        f"Seeded demo store '{result['store_id']}' with {result['orders']} orders.\n"
        f"Flagship incident day (Tuesday stockout): {result['incident_day']}\n"
        f"Now run:  python -m scout.agent.run"
    )

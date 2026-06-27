"""SQLAlchemy ORM — the event store Scout owns.

`store_id` is on every table (multi-tenant from day one, even though v1 runs one store).
Point-in-time inventory history and the daily metric series live here because the Admin
API does not retain them — this is the data the flagship finding depends on.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    DateTime,
    Date,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from scout.timeutil import utcnow


class Base(DeclarativeBase):
    pass


class Store(Base):
    __tablename__ = "stores"

    store_id: Mapped[str] = mapped_column(String, primary_key=True)
    domain: Mapped[str] = mapped_column(String, default="")
    timezone: Mapped[str] = mapped_column(String, default="UTC")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OrderSnapshot(Base):
    __tablename__ = "order_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    order_ref: Mapped[str] = mapped_column(String)  # Shopify order name/id
    created_at_store: Mapped[datetime] = mapped_column(DateTime, index=True)
    total_price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String, default="USD")
    financial_status: Mapped[str] = mapped_column(String, default="paid")

    __table_args__ = (
        UniqueConstraint("store_id", "order_ref", name="uq_order_store_ref"),
    )


class OrderLineItem(Base):
    __tablename__ = "order_line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    order_ref: Mapped[str] = mapped_column(String)
    sku: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String, default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    created_at_store: Mapped[datetime] = mapped_column(DateTime, index=True)


class InventoryLevelEvent(Base):
    """Captured from inventory_levels/update webhooks — the timestamped 'hit zero at 2pm'
    history the Admin API does not provide."""

    __tablename__ = "inventory_level_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    sku: Mapped[str] = mapped_column(String, index=True)
    variant_id: Mapped[str] = mapped_column(String, default="")
    location_id: Mapped[str] = mapped_column(String, default="")
    available: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)

    __table_args__ = (
        Index("ix_inv_store_sku_time", "store_id", "sku", "occurred_at"),
    )


class VariantMap(Base):
    """Maps a Shopify inventory_item_id -> sku/variant per store. The
    inventory_levels/update webhook carries inventory_item_id, NOT sku, so we resolve it
    here. Populated by scout.capture.variant_sync against the live store."""

    __tablename__ = "variant_map"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    inventory_item_id: Mapped[str] = mapped_column(String, index=True)
    sku: Mapped[str] = mapped_column(String, default="")
    variant_id: Mapped[str] = mapped_column(String, default="")

    __table_args__ = (
        UniqueConstraint("store_id", "inventory_item_id", name="uq_variant_store_item"),
    )


class MetricTimeseries(Base):
    """One row per (store, metric, day). `weekday` is denormalised so same-weekday
    baselines are a cheap filtered query."""

    __tablename__ = "metric_timeseries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    metric: Mapped[str] = mapped_column(String, index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    weekday: Mapped[int] = mapped_column(Integer, index=True)  # 0=Mon .. 6=Sun
    value: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("store_id", "metric", "day", name="uq_metric_store_day"),
    )


class FindingRecord(Base):
    """Persisted Finding (Phase 4). Full Finding payload kept as JSON text for the API."""

    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(String, index=True)
    headline: Mapped[str] = mapped_column(String)
    confirmed_cause: Mapped[str] = mapped_column(String, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    payload_json: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

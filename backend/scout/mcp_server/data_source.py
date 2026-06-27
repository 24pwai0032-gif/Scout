"""Data source behind the MCP tools.

- DemoDataSource reads the locally-seeded event store (explicit demo mode).
- ShopifyDataSource reads the live Admin API via ShopifyClient.
- get_inventory_events() ALWAYS reads OUR captured store (both modes) — it is history
  Shopify does not retain.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select

from scout.capture.db import session_scope
from scout.capture.schema import InventoryLevelEvent, OrderLineItem, OrderSnapshot
from scout.config import DataSource, Settings
from scout.logging_config import get_logger
from scout.timeutil import utcnow

log = get_logger("scout.mcp.datasource")


def _parse_day(value: str) -> date:
    return date.fromisoformat(value[:10])


def _unit_price(line_item: dict) -> float:
    """Per-unit discounted price from a Shopify line item, robust to missing fields."""
    try:
        return float(line_item["discountedUnitPriceSet"]["shopMoney"]["amount"])
    except (KeyError, TypeError, ValueError):
        return 0.0


class BaseDataSource:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store_id = settings.store_id

    # Shared: captured inventory history (never live Shopify).
    def get_inventory_events(self, start: str, end: str) -> list[dict]:
        d0 = datetime.combine(_parse_day(start), time.min)
        d1 = datetime.combine(_parse_day(end), time.max)
        with session_scope() as s:
            rows = s.execute(
                select(InventoryLevelEvent)
                .where(
                    InventoryLevelEvent.store_id == self.store_id,
                    InventoryLevelEvent.occurred_at >= d0,
                    InventoryLevelEvent.occurred_at <= d1,
                )
                .order_by(InventoryLevelEvent.occurred_at)
            ).scalars().all()
            out = [
                {
                    "sku": r.sku,
                    "available": r.available,
                    "occurred_at": r.occurred_at.isoformat(),
                    "location_id": r.location_id,
                }
                for r in rows
            ]
        log.info("get_inventory_events", store_id=self.store_id, count=len(out))
        return out


class DemoDataSource(BaseDataSource):
    def get_orders(self, start_date: str, end_date: str) -> list[dict]:
        d0 = datetime.combine(_parse_day(start_date), time.min)
        d1 = datetime.combine(_parse_day(end_date), time.max)
        with session_scope() as s:
            orders = s.execute(
                select(OrderSnapshot).where(
                    OrderSnapshot.store_id == self.store_id,
                    OrderSnapshot.created_at_store >= d0,
                    OrderSnapshot.created_at_store <= d1,
                )
            ).scalars().all()
            items = s.execute(
                select(OrderLineItem).where(
                    OrderLineItem.store_id == self.store_id,
                    OrderLineItem.created_at_store >= d0,
                    OrderLineItem.created_at_store <= d1,
                )
            ).scalars().all()
        by_ref: dict[str, list] = {}
        for li in items:
            by_ref.setdefault(li.order_ref, []).append(
                {"sku": li.sku, "title": li.title, "quantity": li.quantity, "price": li.price}
            )
        result = [
            {
                "order_ref": o.order_ref,
                "created_at": o.created_at_store.isoformat(),
                "total_price": o.total_price,
                "financial_status": o.financial_status,
                "line_items": by_ref.get(o.order_ref, []),
            }
            for o in orders
        ]
        log.info("get_orders", store_id=self.store_id, count=len(result))
        return result

    def get_inventory_levels(self) -> list[dict]:
        with session_scope() as s:
            # Latest event per sku = current level.
            sub = (
                select(
                    InventoryLevelEvent.sku,
                    func.max(InventoryLevelEvent.occurred_at).label("mx"),
                )
                .where(InventoryLevelEvent.store_id == self.store_id)
                .group_by(InventoryLevelEvent.sku)
                .subquery()
            )
            rows = s.execute(
                select(InventoryLevelEvent).join(
                    sub,
                    (InventoryLevelEvent.sku == sub.c.sku)
                    & (InventoryLevelEvent.occurred_at == sub.c.mx),
                ).where(InventoryLevelEvent.store_id == self.store_id)
            ).scalars().all()
            titles = dict(
                s.execute(
                    select(OrderLineItem.sku, func.max(OrderLineItem.title)).where(
                        OrderLineItem.store_id == self.store_id
                    ).group_by(OrderLineItem.sku)
                ).all()
            )
        return [
            {"sku": r.sku, "title": titles.get(r.sku, r.sku), "available": r.available}
            for r in rows
        ]

    def get_product_metrics(self, product_id: str) -> dict:
        """product_id == sku in demo. Units/revenue over the trailing 7 days + stock."""
        d1 = utcnow()
        d0 = d1 - timedelta(days=7)
        with session_scope() as s:
            units, revenue = s.execute(
                select(
                    func.coalesce(func.sum(OrderLineItem.quantity), 0),
                    func.coalesce(func.sum(OrderLineItem.quantity * OrderLineItem.price), 0.0),
                ).where(
                    OrderLineItem.store_id == self.store_id,
                    OrderLineItem.sku == product_id,
                    OrderLineItem.created_at_store >= d0,
                )
            ).one()
        levels = {lvl["sku"]: lvl["available"] for lvl in self.get_inventory_levels()}
        return {
            "sku": product_id,
            "units_sold_7d": int(units),
            "revenue_7d": round(float(revenue), 2),
            "current_stock": levels.get(product_id, 0),
        }

    def get_order_velocity(self, sku: str, window: int = 14) -> dict:
        d1 = utcnow()
        d0 = d1 - timedelta(days=window)
        with session_scope() as s:
            units = s.execute(
                select(func.coalesce(func.sum(OrderLineItem.quantity), 0)).where(
                    OrderLineItem.store_id == self.store_id,
                    OrderLineItem.sku == sku,
                    OrderLineItem.created_at_store >= d0,
                )
            ).scalar_one()
        per_day = round(float(units) / window, 3) if window else 0.0
        return {"sku": sku, "units": int(units), "window_days": window, "per_day": per_day}


class ShopifyDataSource(BaseDataSource):
    """Live Admin API. Wired for the 'shopify' path; demo mode is the verified one."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        from scout.mcp_server.shopify_client import ShopifyClient

        self.client = ShopifyClient(settings)

    def get_orders(self, start_date: str, end_date: str) -> list[dict]:
        query = """
        query($q: String!, $after: String) {
          orders(first: 100, after: $after, query: $q) {
            pageInfo { hasNextPage endCursor }
            nodes {
              name createdAt displayFinancialStatus
              currentTotalPriceSet { shopMoney { amount } }
              lineItems(first: 50) {
                nodes {
                  quantity title sku
                  discountedUnitPriceSet { shopMoney { amount } }
                }
              }
            }
          }
        }"""
        q = f"created_at:>='{start_date}' AND created_at:<='{end_date}'"
        out = []
        for n in self.client.paginate(query, ["orders"], {"q": q}):
            out.append(
                {
                    "order_ref": n["name"],
                    "created_at": n["createdAt"],
                    "total_price": float(n["currentTotalPriceSet"]["shopMoney"]["amount"]),
                    "financial_status": n["displayFinancialStatus"],
                    "line_items": [
                        {
                            "sku": li["sku"],
                            "title": li["title"],
                            "quantity": li["quantity"],
                            "price": _unit_price(li),
                        }
                        for li in n["lineItems"]["nodes"]
                    ],
                }
            )
        return out

    def get_inventory_levels(self) -> list[dict]:
        query = """
        query($after: String) {
          productVariants(first: 100, after: $after) {
            pageInfo { hasNextPage endCursor }
            nodes { sku displayName inventoryQuantity }
          }
        }"""
        return [
            {"sku": n["sku"] or "", "title": n["displayName"], "available": n["inventoryQuantity"] or 0}
            for n in self.client.paginate(query, ["productVariants"])
        ]

    def get_product_metrics(self, product_id: str) -> dict:
        """Trailing-7-day units + revenue for a SKU, plus current stock — parity with demo."""
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=7)).isoformat()
        units = revenue = 0.0
        for o in self.get_orders(start, end):
            for li in o["line_items"]:
                if li["sku"] == product_id:
                    units += li["quantity"]
                    revenue += li["quantity"] * li["price"]
        levels = {lvl["sku"]: lvl["available"] for lvl in self.get_inventory_levels()}
        return {
            "sku": product_id,
            "units_sold_7d": int(units),
            "revenue_7d": round(revenue, 2),
            "current_stock": levels.get(product_id, 0),
        }

    def get_order_velocity(self, sku: str, window: int = 14) -> dict:
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=window)).isoformat()
        units = sum(
            li["quantity"]
            for o in self.get_orders(start, end)
            for li in o["line_items"]
            if li["sku"] == sku
        )
        return {"sku": sku, "units": units, "window_days": window, "per_day": round(units / window, 3)}


def make_data_source(settings: Settings) -> BaseDataSource:
    settings.require_shopify()
    if settings.data_source is DataSource.shopify:
        log.info("data_source_selected", source="shopify")
        return ShopifyDataSource(settings)
    log.info("data_source_selected", source="demo")
    return DemoDataSource(settings)

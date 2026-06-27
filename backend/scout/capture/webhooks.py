"""Webhook HMAC verification + persistence of orders/create and inventory_levels/update.

Every inbound webhook is HMAC-verified; forgeries are rejected and logged. The FastAPI
receiver (Phase 4) calls these after verifying the signature.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime

from scout.capture.db import session_scope
from scout.capture.schema import InventoryLevelEvent, OrderLineItem, OrderSnapshot, VariantMap
from scout.logging_config import get_logger
from scout.timeutil import utcnow

log = get_logger("scout.capture.webhooks")


def verify_hmac(secret: str, body: bytes, header_b64: str | None) -> bool:
    """Constant-time check of Shopify's base64 HMAC-SHA256 header."""
    if not secret or not header_b64:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, header_b64)


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return utcnow()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return utcnow()


def handle_orders_create(store_id: str, payload: dict) -> None:
    order_ref = str(payload.get("name") or payload.get("id"))
    created = _parse_dt(payload.get("created_at"))
    with session_scope() as s:
        # Idempotent: skip if we already captured this order.
        exists = (
            s.query(OrderSnapshot)
            .filter_by(store_id=store_id, order_ref=order_ref)
            .first()
        )
        if exists:
            log.info("order_already_captured", store_id=store_id, order_ref=order_ref)
            return
        s.add(
            OrderSnapshot(
                store_id=store_id,
                order_ref=order_ref,
                created_at_store=created,
                total_price=float(payload.get("total_price", 0) or 0),
                currency=payload.get("currency", "USD"),
                financial_status=payload.get("financial_status", "paid"),
            )
        )
        for li in payload.get("line_items", []):
            s.add(
                OrderLineItem(
                    store_id=store_id,
                    order_ref=order_ref,
                    sku=li.get("sku") or li.get("title") or "(unknown)",
                    title=li.get("title", ""),
                    quantity=int(li.get("quantity", 0)),
                    price=float(li.get("price", 0) or 0),
                    created_at_store=created,
                )
            )
    log.info("order_captured", store_id=store_id, order_ref=order_ref)


def _resolve_sku(session, store_id: str, inventory_item_id: str) -> str:
    """inventory_item_id -> sku via the variant_map (populated by variant_sync)."""
    if not inventory_item_id:
        return ""
    row = (
        session.query(VariantMap)
        .filter_by(store_id=store_id, inventory_item_id=str(inventory_item_id))
        .first()
    )
    return row.sku if row else ""


def handle_inventory_update(store_id: str, payload: dict) -> None:
    """Persist a point-in-time inventory level. The real webhook carries
    inventory_item_id (not sku), so we resolve via variant_map. The demo passes sku
    directly. If neither yields a sku we still capture the event but log LOUDLY — a blank
    sku means variant_sync hasn't run, not that the data is fine."""
    inventory_item_id = str(payload.get("inventory_item_id", ""))
    with session_scope() as s:
        sku = payload.get("sku") or _resolve_sku(s, store_id, inventory_item_id)
        if not sku:
            log.warning(
                "inventory_sku_unresolved",
                store_id=store_id,
                inventory_item_id=inventory_item_id,
                hint="run scout.capture.variant_sync to populate variant_map",
            )
        s.add(
            InventoryLevelEvent(
                store_id=store_id,
                sku=sku,
                variant_id=inventory_item_id,
                location_id=str(payload.get("location_id", "")),
                available=int(payload.get("available", 0)),
                occurred_at=_parse_dt(payload.get("updated_at")),
            )
        )
    log.info("inventory_event_captured", store_id=store_id, sku=sku, available=payload.get("available"))

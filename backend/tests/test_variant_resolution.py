"""Live webhooks carry inventory_item_id, not sku — verify we resolve via variant_map."""

from scout.capture.db import init_db, session_scope
from scout.capture.schema import InventoryLevelEvent, VariantMap
from scout.capture.webhooks import handle_inventory_update


def test_inventory_update_resolves_sku_from_map():
    init_db()
    with session_scope() as s:
        s.merge(VariantMap(store_id="demo-store", inventory_item_id="424242", sku="RESOLVED-SKU"))

    # Real-shaped payload: NO sku, only inventory_item_id.
    handle_inventory_update("demo-store", {
        "inventory_item_id": 424242, "location_id": 1, "available": 3,
        "updated_at": "2026-06-23T10:00:00Z",
    })

    with session_scope() as s:
        ev = (
            s.query(InventoryLevelEvent)
            .filter_by(store_id="demo-store", variant_id="424242")
            .order_by(InventoryLevelEvent.id.desc())
            .first()
        )
    assert ev is not None
    assert ev.sku == "RESOLVED-SKU"   # resolved, not blank


def test_demo_payload_with_sku_still_works():
    handle_inventory_update("demo-store", {
        "sku": "DIRECT-SKU", "inventory_item_id": 1, "location_id": 1,
        "available": 0, "updated_at": "2026-06-23T14:00:00Z",
    })
    with session_scope() as s:
        ev = (
            s.query(InventoryLevelEvent)
            .filter_by(store_id="demo-store", sku="DIRECT-SKU")
            .first()
        )
    assert ev is not None

"""Populate variant_map (inventory_item_id -> sku) from the live Shopify store.

Run after Step Zero and whenever products/variants change, so inventory_levels/update
webhooks (which carry inventory_item_id, not sku) can be resolved to a SKU.

    python -m scout.capture.variant_sync          # requires SCOUT_DATA_SOURCE=shopify
"""

from __future__ import annotations

from scout.capture.db import init_db, session_scope
from scout.capture.schema import VariantMap
from scout.config import DataSource, get_settings
from scout.logging_config import configure_logging, get_logger

log = get_logger("scout.capture.variant_sync")

_QUERY = """
query($after: String) {
  productVariants(first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { id sku inventoryItem { id } }
  }
}
"""


def sync_variant_map(store_id: str | None = None) -> int:
    settings = get_settings()
    store_id = store_id or settings.store_id
    if settings.data_source is not DataSource.shopify:
        log.warning("variant_sync_skipped", reason="SCOUT_DATA_SOURCE!=shopify (demo sets sku directly)")
        return 0

    from scout.mcp_server.shopify_client import ShopifyClient

    init_db()
    client = ShopifyClient(settings)
    count = 0
    try:
        with session_scope() as s:
            for n in client.paginate(_QUERY, ["productVariants"]):
                gid = (n.get("inventoryItem") or {}).get("id", "")
                item_id = gid.split("/")[-1] if gid else ""
                if not item_id:
                    continue
                sku = n.get("sku") or ""
                row = (
                    s.query(VariantMap)
                    .filter_by(store_id=store_id, inventory_item_id=item_id)
                    .first()
                )
                if row:
                    row.sku, row.variant_id = sku, n.get("id", "")
                else:
                    s.add(VariantMap(
                        store_id=store_id, inventory_item_id=item_id,
                        sku=sku, variant_id=n.get("id", ""),
                    ))
                count += 1
    finally:
        client.close()
    log.info("variant_map_synced", store_id=store_id, variants=count)
    return count


if __name__ == "__main__":
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    n = sync_variant_map()
    print(f"Synced {n} variants into variant_map for store '{s.store_id}'.")

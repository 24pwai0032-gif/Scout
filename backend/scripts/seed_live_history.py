"""Seed BACKDATED synthetic history from your REAL Shopify catalog.

Reads your actual orders (to learn the SKUs, prices, and sales mix) and current stock,
then generates ~8 weeks of backdated orders + a stockout incident into Scout's own
capture DB under a SEPARATE store id (`<store>-sim`). This is clearly-labeled synthetic
history for demoing on your real products WITHOUT waiting weeks — it never touches Shopify
and never mixes with your real captured store.

    # requires SCOUT_DATA_SOURCE=shopify + creds (to read the catalog)
    python scripts/seed_live_history.py

Then investigate it (reads our DB, real product names):
    SCOUT_DATA_SOURCE=demo SCOUT_STORE_ID=<store>-sim python -m scout.agent.run
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta

from scout.capture.seed_demo import Product, seed_history
from scout.config import DataSource, get_settings
from scout.logging_config import configure_logging, get_logger
from scout.mcp_server.data_source import make_data_source

log = get_logger("scout.seed_live")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    if settings.data_source is not DataSource.shopify:
        sys.exit("Set SCOUT_DATA_SOURCE=shopify (+ creds) so we can read your real catalog.")

    src = make_data_source(settings)
    try:
        end = date.today()
        orders = src.get_orders(str(end - timedelta(days=30)), str(end))
        levels = {lvl["sku"]: lvl for lvl in src.get_inventory_levels() if lvl.get("sku")}
    finally:
        client = getattr(src, "client", None)
        if client is not None:
            client.close()

    # Learn real revenue mix + average unit price per SKU from actual orders.
    revenue: dict[str, float] = defaultdict(float)
    prices: dict[str, list] = defaultdict(list)
    titles: dict[str, str] = {}
    for o in orders:
        for li in o["line_items"]:
            sku = li.get("sku")
            price = li.get("price") or 0.0
            if not sku or price <= 0:
                continue
            revenue[sku] += li["quantity"] * price
            prices[sku].append(price)
            titles[sku] = li.get("title") or sku

    if not revenue:
        sys.exit(
            "No real orders with priced SKUs found in the last 30 days. Create a few "
            "orders of your tracked products first, then re-run."
        )

    total = sum(revenue.values())
    products = [
        Product(
            sku=sku,
            title=titles[sku],
            price=round(sum(prices[sku]) / len(prices[sku]), 2),
            fraction=revenue[sku] / total,
            current_stock=int(levels.get(sku, {}).get("available", 50) or 0),
        )
        for sku in revenue
    ]
    top_sku = max(products, key=lambda p: p.fraction).sku        # biggest revenue driver
    jitter_sku = min(products, key=lambda p: p.price).sku        # cheapest → small variance
    sim_store = f"{settings.store_id}-sim"

    result = seed_history(
        sim_store, products, top_sku, jitter_sku=jitter_sku,
        domain=settings.shopify_store_domain or "",
    )

    print("\nSeeded SYNTHETIC backdated history from your real catalog:")
    print(f"  store id (synthetic):  {sim_store}")
    print(f"  products (from orders): {', '.join(p.sku for p in products)}")
    print(f"  stockout SKU (incident): {top_sku} ({titles[top_sku]})")
    print(f"  incident day:          {result['incident_day']}")
    print(f"  backdated orders:      {result['orders']}")
    print("\nNow investigate it (reads our DB, your real product names):")
    print(f"  SCOUT_DATA_SOURCE=demo SCOUT_STORE_ID={sim_store} python -m scout.agent.run")


if __name__ == "__main__":
    main()

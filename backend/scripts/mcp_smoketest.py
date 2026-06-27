"""Phase 1 deliverable — spin up the MCP server and call every tool end-to-end.

    python scripts/mcp_smoketest.py

Uses the configured data source (demo by default; SCOUT_DATA_SOURCE=shopify for live).
Transport defaults to real MCP stdio; set SCOUT_MCP_TRANSPORT=inprocess to skip the
subprocess.
"""

from __future__ import annotations

from datetime import date, timedelta

from scout.agent.mcp_client import make_tools
from scout.config import get_settings
from scout.logging_config import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    tools = make_tools(settings)
    today = date.today()
    week_ago = today - timedelta(days=7)
    try:
        print("get_orders:", len(tools.get_orders(str(week_ago), str(today))), "orders")
        levels = tools.get_inventory_levels()
        with_sku = [lvl for lvl in levels if lvl.get("sku")]
        print(f"get_inventory_levels: {len(levels)} variants ({len(with_sku)} with a SKU)")
        print("  sample with SKU:", with_sku[:2] or "(none — products have no SKUs!)")
        if with_sku:
            sku = with_sku[0]["sku"]
            print("get_product_metrics:", tools.get_product_metrics(sku))
            print("get_order_velocity:", tools.get_order_velocity(sku, 14))
        print("get_inventory_events:", len(tools.get_inventory_events(str(week_ago), str(today))), "events")
        print("\nAll five MCP tools responded.")
    finally:
        tools.close()


if __name__ == "__main__":
    main()

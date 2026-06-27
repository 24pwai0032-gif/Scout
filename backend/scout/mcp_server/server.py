"""The custom MCP server process. Exposes Scout's tools over stdio using the official
`mcp` SDK. The LangGraph agent connects to THIS as an MCP client.

Run standalone:  python -m scout.mcp_server.server
"""

from __future__ import annotations

from scout.config import get_settings
from scout.logging_config import configure_logging, get_logger
from scout.mcp_server.data_source import make_data_source

log = get_logger("scout.mcp.server")

_settings = get_settings()
configure_logging(_settings.log_level, _settings.log_json)
_source = make_data_source(_settings)


def _build_server():
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("scout-shopify")

    @mcp.tool()
    def get_orders(start_date: str, end_date: str) -> list[dict]:
        """Orders (with line items) created between start_date and end_date (ISO dates)."""
        log.info("tool_call", tool="get_orders", start=start_date, end=end_date)
        return _source.get_orders(start_date, end_date)

    @mcp.tool()
    def get_inventory_levels() -> list[dict]:
        """Current inventory level per SKU."""
        log.info("tool_call", tool="get_inventory_levels")
        return _source.get_inventory_levels()

    @mcp.tool()
    def get_product_metrics(product_id: str) -> dict:
        """Trailing units sold, revenue, and current stock for a product/SKU."""
        log.info("tool_call", tool="get_product_metrics", product_id=product_id)
        return _source.get_product_metrics(product_id)

    @mcp.tool()
    def get_order_velocity(sku: str, window: int = 14) -> dict:
        """Units/day for a SKU over the trailing `window` days."""
        log.info("tool_call", tool="get_order_velocity", sku=sku, window=window)
        return _source.get_order_velocity(sku, window)

    @mcp.tool()
    def get_inventory_events(start: str, end: str) -> list[dict]:
        """Timestamped inventory level changes from OUR captured store (not live Shopify)."""
        log.info("tool_call", tool="get_inventory_events", start=start, end=end)
        return _source.get_inventory_events(start, end)

    return mcp


def main() -> None:
    log.info("mcp_server_starting", data_source=_settings.data_source.value)
    _build_server().run()  # stdio transport


if __name__ == "__main__":
    main()

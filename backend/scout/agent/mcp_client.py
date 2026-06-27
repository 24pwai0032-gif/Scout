"""MCP client the agent uses. Exposes a synchronous `Tools` surface to the routines.

Transports:
  * "stdio"     — real MCP: spawns the Scout MCP server and talks to it over stdio using
                  the official `mcp` SDK. This is the production architecture (the agent
                  is an MCP client and never imports Shopify directly).
  * "inprocess" — calls the same data source directly, no subprocess. Sanctioned for the
                  offline eval/test path and for the demo when the `mcp` package isn't
                  installed. EXPLICIT (SCOUT_MCP_TRANSPORT), never a silent prod fallback.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from typing import Any

from scout.config import Settings, get_settings
from scout.logging_config import get_logger

log = get_logger("scout.agent.mcp_client")


class InProcessTools:
    """Direct data-source transport (offline/eval)."""

    def __init__(self, settings: Settings):
        from scout.mcp_server.data_source import make_data_source

        self._src = make_data_source(settings)

    def get_orders(self, start_date: str, end_date: str) -> list[dict]:
        return self._src.get_orders(start_date, end_date)

    def get_inventory_levels(self) -> list[dict]:
        return self._src.get_inventory_levels()

    def get_product_metrics(self, product_id: str) -> dict:
        return self._src.get_product_metrics(product_id)

    def get_order_velocity(self, sku: str, window: int = 14) -> dict:
        return self._src.get_order_velocity(sku, window)

    def get_inventory_events(self, start: str, end: str) -> list[dict]:
        return self._src.get_inventory_events(start, end)

    def close(self) -> None:  # symmetry with the stdio client
        pass


_STOP = object()


class StdioMcpTools:
    """Real MCP-over-stdio client wrapped in a sync facade.

    The MCP session (anyio task groups) is entered AND exited inside ONE long-lived task
    on a background event loop. Sync calls hand work to that task via a queue and block on
    a concurrent.futures.Future — so cancel scopes are never crossed between tasks.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._queue: asyncio.Queue | None = None
        self._ready = threading.Event()
        self._serve_future = asyncio.run_coroutine_threadsafe(self._serve(), self._loop)
        if not self._ready.wait(timeout=30):
            raise RuntimeError("MCP stdio server failed to start within 30s")

    async def _serve(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable, args=["-m", "scout.mcp_server.server"], env={**os.environ}
        )
        self._queue = asyncio.Queue()
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                log.info("mcp_stdio_connected")
                self._ready.set()
                while True:
                    item = await self._queue.get()
                    if item is _STOP:
                        return
                    name, args, fut = item
                    try:
                        fut.set_result(await self._call(session, name, args))
                    except Exception as exc:  # surface to the caller's .result()
                        fut.set_exception(exc)

    async def _call(self, session, name: str, args: dict) -> Any:
        result = await session.call_tool(name, args)
        texts = [t for b in result.content if (t := getattr(b, "text", None)) is not None]
        if getattr(result, "isError", False):
            raise RuntimeError(f"MCP tool '{name}' error: {' '.join(texts) or 'unknown'}")
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            return structured.get("result", structured)
        for text in texts:
            return json.loads(text)
        return None

    def _invoke(self, name: str, args: dict) -> Any:
        from concurrent.futures import Future

        fut: Future = Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (name, args, fut))
        return fut.result(timeout=30)

    def get_orders(self, start_date: str, end_date: str) -> list[dict]:
        return self._invoke("get_orders", {"start_date": start_date, "end_date": end_date})

    def get_inventory_levels(self) -> list[dict]:
        return self._invoke("get_inventory_levels", {})

    def get_product_metrics(self, product_id: str) -> dict:
        return self._invoke("get_product_metrics", {"product_id": product_id})

    def get_order_velocity(self, sku: str, window: int = 14) -> dict:
        return self._invoke("get_order_velocity", {"sku": sku, "window": window})

    def get_inventory_events(self, start: str, end: str) -> list[dict]:
        return self._invoke("get_inventory_events", {"start": start, "end": end})

    def close(self) -> None:
        try:
            if self._queue is not None:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, _STOP)
                self._serve_future.result(timeout=10)  # let the single task unwind cleanly
        except Exception as exc:  # never let teardown lose a finding
            log.warning("mcp_stdio_shutdown_error", error=str(exc))
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)


def make_tools(settings: Settings | None = None):
    settings = settings or get_settings()
    transport = os.environ.get("SCOUT_MCP_TRANSPORT", "stdio").lower()
    if transport == "inprocess":
        log.info("mcp_transport", transport="inprocess")
        return InProcessTools(settings)
    log.info("mcp_transport", transport="stdio")
    return StdioMcpTools(settings)

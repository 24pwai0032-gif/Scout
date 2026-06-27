"""Shopify Admin GraphQL client. Owns auth, retry/rate-limiting, and cursor pagination
so those concerns never reach the agent.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

import httpx

from scout.config import Settings
from scout.logging_config import get_logger

log = get_logger("scout.mcp.shopify")


class ShopifyClient:
    def __init__(self, settings: Settings):
        if not (settings.shopify_store_domain and settings.shopify_admin_token):
            raise RuntimeError("Shopify client requires SHOPIFY_STORE_DOMAIN + token.")
        self._url = (
            f"https://{settings.shopify_store_domain}"
            f"/admin/api/{settings.shopify_api_version}/graphql.json"
        )
        self._headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": settings.shopify_admin_token,
        }
        self._client = httpx.Client(timeout=30.0)

    def execute(self, query: str, variables: dict | None = None, _retries: int = 5) -> dict:
        for attempt in range(_retries):
            resp = self._client.post(
                self._url, headers=self._headers, json={"query": query, "variables": variables or {}}
            )
            if resp.status_code == 429:  # throttled
                wait = float(resp.headers.get("Retry-After", 2.0))
                log.warning("shopify_throttled", attempt=attempt, wait=wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("errors"):
                # Cost throttling surfaces inside `errors` too.
                if _is_throttled(payload):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"Shopify GraphQL errors: {payload['errors']}")
            return payload["data"]
        raise RuntimeError("Shopify GraphQL: exhausted retries (throttled).")

    def paginate(
        self, query: str, connection_path: list[str], variables: dict | None = None
    ) -> Iterator[dict]:
        """Yield nodes across all pages. `connection_path` walks data -> connection."""
        after = None
        variables = dict(variables or {})
        while True:
            variables["after"] = after
            data = self.execute(query, variables)
            conn: Any = data
            for key in connection_path:
                conn = conn[key]
            yield from conn["nodes"]
            if conn["pageInfo"]["hasNextPage"]:
                after = conn["pageInfo"]["endCursor"]
            else:
                return

    def close(self) -> None:
        self._client.close()


def _is_throttled(payload: dict) -> bool:
    for err in payload.get("errors", []):
        if "throttle" in str(err).lower():
            return True
    return False

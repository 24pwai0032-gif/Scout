"""Cassette tooling: record real tool outputs to JSON, replay them deterministically.

A cassette captures every (tool, args) -> result for a case so the agent can be replayed
offline. This is the explicit test fixture path (kept out of runtime code).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CASSETTE_DIR = Path(__file__).parent / "cassettes"


def _key(name: str, args: dict) -> str:
    return name + "|" + json.dumps(args, sort_keys=True, default=str)


class RecordingTools:
    """Wraps a real Tools impl and records every call."""

    def __init__(self, inner):
        self._inner = inner
        self._log: dict[str, Any] = {}

    def _wrap(self, name: str, args: dict, value):
        self._log[_key(name, args)] = value
        return value

    def get_orders(self, start_date, end_date):
        return self._wrap("get_orders", {"start_date": start_date, "end_date": end_date},
                          self._inner.get_orders(start_date, end_date))

    def get_inventory_levels(self):
        return self._wrap("get_inventory_levels", {}, self._inner.get_inventory_levels())

    def get_product_metrics(self, product_id):
        return self._wrap("get_product_metrics", {"product_id": product_id},
                          self._inner.get_product_metrics(product_id))

    def get_order_velocity(self, sku, window=14):
        return self._wrap("get_order_velocity", {"sku": sku, "window": window},
                          self._inner.get_order_velocity(sku, window))

    def get_inventory_events(self, start, end):
        return self._wrap("get_inventory_events", {"start": start, "end": end},
                          self._inner.get_inventory_events(start, end))

    def close(self):
        if hasattr(self._inner, "close"):
            self._inner.close()

    def save(self, name: str):
        CASSETTE_DIR.mkdir(parents=True, exist_ok=True)
        (CASSETTE_DIR / f"{name}.json").write_text(json.dumps(self._log, indent=2, default=str))


class CassetteTools:
    """Replays a saved cassette. Raises if a call wasn't recorded (keeps tests honest)."""

    def __init__(self, name: str):
        data = (CASSETTE_DIR / f"{name}.json").read_text()
        self._log = json.loads(data)

    def _get(self, name: str, args: dict):
        k = _key(name, args)
        if k not in self._log:
            raise KeyError(f"cassette miss: {k}")
        return self._log[k]

    def get_orders(self, start_date, end_date):
        return self._get("get_orders", {"start_date": start_date, "end_date": end_date})

    def get_inventory_levels(self):
        return self._get("get_inventory_levels", {})

    def get_product_metrics(self, product_id):
        return self._get("get_product_metrics", {"product_id": product_id})

    def get_order_velocity(self, sku, window=14):
        return self._get("get_order_velocity", {"sku": sku, "window": window})

    def get_inventory_events(self, start, end):
        return self._get("get_inventory_events", {"start": start, "end": end})

    def close(self):
        pass

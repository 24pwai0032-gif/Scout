"""Send a correctly-HMAC-signed sample webhook to a locally running Scout API.

    python scripts/send_test_webhook.py [orders/create|inventory_levels/update]

Signs with SHOPIFY_WEBHOOK_SECRET so the receiver accepts it (proves HMAC verification +
debounced enqueue). A wrong secret should yield HTTP 401.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys

import httpx

API_URL = os.environ.get("SCOUT_API_URL", "http://localhost:8000")
SECRET = os.environ.get("SHOPIFY_WEBHOOK_SECRET", "test-secret")

SAMPLES = {
    "orders/create": {
        "id": 9001, "name": "#TEST-9001", "created_at": "2026-06-23T15:00:00Z",
        "total_price": "50.00", "currency": "USD", "financial_status": "paid",
        "line_items": [{"sku": "TEE-BLK-M", "title": "Black Tee — M", "quantity": 2, "price": "25.00"}],
    },
    "inventory_levels/update": {
        "inventory_item_id": 555, "location_id": 1, "available": 0,
        "updated_at": "2026-06-23T14:00:00Z", "sku": "TEE-BLK-M",
    },
}


def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else "orders/create"
    payload = json.dumps(SAMPLES[topic]).encode("utf-8")
    digest = hmac.new(SECRET.encode(), payload, hashlib.sha256).digest()
    sig = base64.b64encode(digest).decode()
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Topic": topic,
        "X-Shopify-Hmac-Sha256": sig,
        "X-Shopify-Shop-Domain": "demo.myshopify.com",
    }
    r = httpx.post(f"{API_URL}/webhooks/shopify", content=payload, headers=headers, timeout=30)
    print(f"{topic}: HTTP {r.status_code} {r.text}")


if __name__ == "__main__":
    main()

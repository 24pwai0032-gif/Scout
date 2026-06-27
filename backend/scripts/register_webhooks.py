"""Phase 0.5 deliverable — register Shopify webhooks against your dev store.

    python scripts/register_webhooks.py https://your-public-host/webhooks/shopify

Requires SCOUT_DATA_SOURCE=shopify and Shopify creds in env. Registers orders/create and
inventory_levels/update. Shopify must be able to reach the callback URL (use a tunnel like
ngrok/cloudflared in local dev).
"""

from __future__ import annotations

import sys

import httpx

from scout.config import get_settings

TOPICS = ["orders/create", "inventory_levels/update"]


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: python scripts/register_webhooks.py <callback_url>")
    callback = sys.argv[1]
    s = get_settings()
    if not (s.shopify_store_domain and s.shopify_admin_token):
        sys.exit("Set SHOPIFY_STORE_DOMAIN and SHOPIFY_ADMIN_TOKEN first.")
    base = f"https://{s.shopify_store_domain}/admin/api/{s.shopify_api_version}"
    headers = {"X-Shopify-Access-Token": s.shopify_admin_token, "Content-Type": "application/json"}
    with httpx.Client(timeout=30) as client:
        for topic in TOPICS:
            body = {"webhook": {"topic": topic, "address": callback, "format": "json"}}
            r = client.post(f"{base}/webhooks.json", headers=headers, json=body)
            if r.status_code in (200, 201):
                print(f"registered {topic} -> {callback}")
            else:
                print(f"FAILED {topic}: {r.status_code} {r.text[:300]}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""
Phase 0 — Manual reconstruction (THROWAWAY honest-test script).

This is NOT part of Scout's repo structure. It exists to answer one question against
your REAL Shopify dev store before any agent is built:

    Can we reconstruct a like-for-like finding such as
    "revenue was down X% vs the last 4 same-weekdays"
    and attribute it to a specific SKU's order velocity,
    using ONLY data the Admin API actually exposes?

It also documents, against real API responses, what we CANNOT reconstruct from the
Admin API alone (expected: point-in-time inventory history, true conversion) — which
determines what the Phase 0.5 event-capture pipeline must build.

Zero pip dependencies — uses only the Python 3.9+ standard library.

------------------------------------------------------------------------------------
SETUP (after Step Zero is done):

  Set these environment variables (PowerShell):
      $env:SHOPIFY_STORE_DOMAIN = "your-store.myshopify.com"
      $env:SHOPIFY_ADMIN_TOKEN  = "shpat_xxxxxxxxxxxxxxxx"
      $env:SHOPIFY_API_VERSION  = "2026-04"   # read the real value from your app

  ...or drop them in a local .env file in this folder (KEY=VALUE per line); this
  script will read it. NEVER commit that file.

RUN:
      python phase0_reconstruct.py 2026-06-23      # the past day to reconstruct
      python phase0_reconstruct.py                 # defaults to last Tuesday

The target day should be a real day with orders. For the flagship test, pick the day
you drove a SKU to a stockout.
------------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# --------------------------------------------------------------------------------------
# Config / credential loading
# --------------------------------------------------------------------------------------


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader so we don't need python-dotenv for a throwaway."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.exit(
            f"ERROR: missing env var {name}. Set it (or add to .env) — see the "
            f"docstring at the top of this file. Refusing to run with fake data."
        )
    return val


_load_dotenv()
STORE_DOMAIN = _require("SHOPIFY_STORE_DOMAIN")
# Accept either name; the token is the same value.
ADMIN_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN") or _require("SHOPIFY_ACCESS_TOKEN")
API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2026-04")

GRAPHQL_URL = f"https://{STORE_DOMAIN}/admin/api/{API_VERSION}/graphql.json"

# Baseline definition for this honest test — mirrors the detection intent from CLAUDE.md:
# compare the target weekday against the trailing SAME-weekday distribution, robustly.
SAME_WEEKDAY_LOOKBACK = 4  # "your last four Tuesdays"


# --------------------------------------------------------------------------------------
# Shopify GraphQL client (just enough for an honest test — pagination included)
# --------------------------------------------------------------------------------------


def graphql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": ADMIN_TOKEN,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        sys.exit(f"HTTP {exc.code} from Shopify: {detail[:600]}")
    except urllib.error.URLError as exc:
        sys.exit(f"Network error reaching Shopify: {exc.reason}")

    if "errors" in payload and payload["errors"]:
        sys.exit("GraphQL errors: " + json.dumps(payload["errors"], indent=2)[:800])
    return payload["data"]


def get_shop_timezone() -> ZoneInfo:
    data = graphql("{ shop { name ianaTimezone currencyCode } }")
    shop = data["shop"]
    print(f"  Connected to: {shop['name']} ({shop['currencyCode']}, {shop['ianaTimezone']})")
    return ZoneInfo(shop["ianaTimezone"])


def fetch_orders(created_at_min_utc: str, created_at_max_utc: str) -> list[dict]:
    """Fetch all orders in a UTC window, following cursor pagination."""
    query = """
    query($q: String!, $after: String) {
      orders(first: 100, after: $after, query: $q) {
        pageInfo { hasNextPage endCursor }
        nodes {
          name
          createdAt
          displayFinancialStatus
          currentTotalPriceSet { shopMoney { amount currencyCode } }
          lineItems(first: 50) {
            nodes { quantity title sku }
          }
        }
      }
    }
    """
    q = f"created_at:>='{created_at_min_utc}' AND created_at:<='{created_at_max_utc}'"
    out: list[dict] = []
    after = None
    while True:
        data = graphql(query, {"q": q, "after": after})
        conn = data["orders"]
        out.extend(conn["nodes"])
        if conn["pageInfo"]["hasNextPage"]:
            after = conn["pageInfo"]["endCursor"]
        else:
            break
    return out


def fetch_current_inventory() -> list[dict]:
    """Current inventory snapshot per variant (this is all the Admin API gives — a
    snapshot, NOT history)."""
    query = """
    query($after: String) {
      productVariants(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          sku
          displayName
          inventoryQuantity
        }
      }
    }
    """
    out: list[dict] = []
    after = None
    while True:
        data = graphql(query, {"after": after})
        conn = data["productVariants"]
        out.extend(conn["nodes"])
        if conn["pageInfo"]["hasNextPage"]:
            after = conn["pageInfo"]["endCursor"]
        else:
            break
    return out


# --------------------------------------------------------------------------------------
# Reconstruction logic
# --------------------------------------------------------------------------------------


def day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[str, str]:
    """Start/end of a store-local calendar day, expressed in UTC ISO8601 for the API."""
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = datetime.combine(day, time.max, tzinfo=tz)
    to_utc = lambda d: d.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    return to_utc(start_local), to_utc(end_local)


def local_day_of(order: dict, tz: ZoneInfo) -> date:
    dt = datetime.fromisoformat(order["createdAt"].replace("Z", "+00:00"))
    return dt.astimezone(tz).date()


def revenue_of(order: dict) -> float:
    return float(order["currentTotalPriceSet"]["shopMoney"]["amount"])


def revenue_for_day(orders: list[dict], day: date, tz: ZoneInfo) -> float:
    return sum(revenue_of(o) for o in orders if local_day_of(o, tz) == day)


def main() -> None:
    # Resolve target day.
    if len(sys.argv) > 1:
        target = date.fromisoformat(sys.argv[1])
    else:
        # default: most recent past Tuesday
        today = date.today()
        offset = (today.weekday() - 1) % 7 or 7
        target = today - timedelta(days=offset)

    weekday_name = target.strftime("%A")
    same_weekdays = [target - timedelta(weeks=k) for k in range(1, SAME_WEEKDAY_LOOKBACK + 1)]

    print("=" * 78)
    print(f"PHASE 0 RECONSTRUCTION — target day {target} ({weekday_name})")
    print("=" * 78)

    tz = get_shop_timezone()

    # One query covers target day + the 4 prior same-weekdays (oldest same-weekday start
    # through target day end).
    window_start, _ = day_bounds_utc(min(same_weekdays), tz)
    _, window_end = day_bounds_utc(target, tz)
    print(f"\n  Pulling orders from {window_start} to {window_end} ...")
    orders = fetch_orders(window_start, window_end)
    print(f"  Got {len(orders)} orders in window.")

    # ---- 1. Revenue: target vs last 4 same-weekdays ---------------------------------
    target_rev = revenue_for_day(orders, target, tz)
    baseline_revs = [revenue_for_day(orders, d, tz) for d in same_weekdays]
    days_with_data = sum(1 for r in baseline_revs if r > 0)

    print("\n--- 1. REVENUE, like-for-like (same weekday) ---")
    print(f"  {target} ({weekday_name}): {target_rev:,.2f}")
    for d, r in zip(same_weekdays, baseline_revs):
        print(f"    prior {d} ({d.strftime('%a')}): {r:,.2f}")

    if days_with_data < 3:
        print(
            f"\n  INSUFFICIENT BASELINE: only {days_with_data} of "
            f"{SAME_WEEKDAY_LOOKBACK} prior same-weekdays have orders. "
            f"Per the brief, we say so rather than guess. Seed/accumulate more history."
        )
    else:
        median_base = statistics.median(baseline_revs)
        # MAD = median absolute deviation (robust spread), previewing detection.
        mad = statistics.median([abs(r - median_base) for r in baseline_revs]) or 1e-9
        deviation_pct = (target_rev - median_base) / median_base * 100 if median_base else 0.0
        robust_z = (target_rev - median_base) / (1.4826 * mad)
        print(f"\n  baseline (median of last {SAME_WEEKDAY_LOOKBACK} {weekday_name}s): {median_base:,.2f}")
        print(f"  deviation: {deviation_pct:+.1f}%   robust z (median+MAD): {robust_z:+.2f}")
        direction = "DOWN" if deviation_pct < 0 else "UP"
        print(
            f"\n  >>> LIKE-FOR-LIKE STATEMENT: revenue was {direction} "
            f"{abs(deviation_pct):.0f}% on {weekday_name} vs your last "
            f"{SAME_WEEKDAY_LOOKBACK} {weekday_name}s. <<<"
        )

    # ---- 2. SKU attribution on the target day ---------------------------------------
    print("\n--- 2. SKU ATTRIBUTION (target day line items) ---")
    sku_qty: dict[str, int] = {}
    for o in orders:
        if local_day_of(o, tz) != target:
            continue
        for li in o["lineItems"]["nodes"]:
            key = li.get("sku") or li.get("title") or "(unknown)"
            sku_qty[key] = sku_qty.get(key, 0) + li["quantity"]
    if sku_qty:
        for sku, qty in sorted(sku_qty.items(), key=lambda kv: -kv[1]):
            print(f"    {qty:>4}  units   {sku}")
        print("  -> We CAN see which SKUs sold (or didn't) on the day from order line items.")
    else:
        print("    (no line items on target day)")

    # ---- 3. Current inventory snapshot ----------------------------------------------
    print("\n--- 3. CURRENT INVENTORY (snapshot only) ---")
    inv = fetch_current_inventory()
    zero = [v for v in inv if (v.get("inventoryQuantity") or 0) <= 0]
    print(f"  {len(inv)} variants; {len(zero)} currently at/below zero.")
    for v in zero[:10]:
        print(f"    OUT: {v.get('sku') or v.get('displayName')}  qty={v.get('inventoryQuantity')}")

    # ---- 4. What the Admin API CANNOT reconstruct -----------------------------------
    print("\n--- 4. WHAT WE CANNOT GET FROM THE ADMIN API ALONE ---")
    print(
        "  * POINT-IN-TIME INVENTORY HISTORY: the API gives only the CURRENT quantity\n"
        "    (section 3). There is no reliable 'this SKU hit zero at 2pm on the target\n"
        "    day' from Admin alone. To attribute a revenue dip to the MOMENT of a\n"
        "    stockout, we must capture inventory_levels/update webhooks ourselves over\n"
        "    time. -> This is exactly what Phase 0.5 builds.\n"
        "  * TRUE CONVERSION: Admin exposes orders, not sessions/traffic. No real\n"
        "    conversion rate is computable here. v1 must use a documented PROXY (e.g.\n"
        "    orders-per-hour) and label it as a proxy, or drop conversion.\n"
        "  * Revenue definition caveat: this script summed currentTotalPriceSet\n"
        "    (includes tax/shipping, reflects later edits/refunds). Decide gross vs net\n"
        "    and financial_status filtering deliberately when building real detection."
    )
    print("\nDone. This confirms what's reconstructable now vs what Phase 0.5 must capture.")


if __name__ == "__main__":
    main()

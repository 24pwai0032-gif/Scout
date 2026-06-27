"""Fixed hypothesis taxonomy + the investigation routine each cause maps to.

The LLM may only SELECT from these causes; every cause has a routine here that calls
real MCP tools and returns evidence + a verdict. A cause with no routine cannot be a
hypothesis (per the brief).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from scout.models import AnomalyEvent, CauseType, Evidence, Verdict


class Tools(Protocol):
    """The MCP tool surface a routine may use (transport-agnostic)."""

    def get_orders(self, start_date: str, end_date: str) -> list[dict]: ...
    def get_inventory_levels(self) -> list[dict]: ...
    def get_product_metrics(self, product_id: str) -> dict: ...
    def get_order_velocity(self, sku: str, window: int = 14) -> dict: ...
    def get_inventory_events(self, start: str, end: str) -> list[dict]: ...


@dataclass
class RoutineResult:
    evidence: list[Evidence] = field(default_factory=list)
    verdict: Verdict = Verdict.INCONCLUSIVE
    confidence: float = 0.0
    specifics: dict = field(default_factory=dict)


def _sku_revenue(orders: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for o in orders:
        for li in o.get("line_items", []):
            out[li["sku"]] = out.get(li["sku"], 0.0) + li["quantity"] * li.get("price", 0.0)
    return out


def _title_for(orders: list[dict], sku: str) -> str:
    for o in orders:
        for li in o.get("line_items", []):
            if li["sku"] == sku and li.get("title"):
                return li["title"]
    return sku


# ── Routines ─────────────────────────────────────────────────────────────────
def routine_stockout(anomaly: AnomalyEvent, tools: Tools, specifics: dict) -> RoutineResult:
    day = anomaly.date
    events = tools.get_inventory_events(day, day)
    ev = [Evidence(
        tool="get_inventory_events", args={"start": day, "end": day},
        result_summary=f"{len(events)} inventory events on {day}",
        supports=None,
    )]
    # Earliest moment any SKU hit zero during the day.
    zero_hits = [e for e in events if e["available"] <= 0]
    if not zero_hits:
        ev[0].supports = False
        return RoutineResult(ev, Verdict.REFUTED, 0.2)
    first = min(zero_hits, key=lambda e: e["occurred_at"])
    t = datetime.fromisoformat(first["occurred_at"])
    sku = first["sku"]
    # Confirm the out-of-stock SKU actually mattered (was selling that day).
    vel = tools.get_order_velocity(sku, window=14)
    ev.append(Evidence(
        tool="get_order_velocity", args={"sku": sku, "window": 14},
        result_summary=f"{sku} averaged {vel['per_day']} units/day before stockout",
        supports=vel["per_day"] > 0,
    ))
    ev[0].supports = True
    ev[0].result_summary = f"{sku} hit 0 units at {t.strftime('%H:%M')} on {day}"
    confidence = 0.9 if vel["per_day"] > 0 else 0.5
    friendly = f"{(t.hour % 12) or 12}{'am' if t.hour < 12 else 'pm'}"  # 14:00 -> '2pm'
    return RoutineResult(
        ev, Verdict.CONFIRMED, confidence,
        {"stockout_sku": sku, "stockout_time": friendly, "stockout_time_24": t.strftime("%H:%M")},
    )


def routine_single_sku_driver(anomaly: AnomalyEvent, tools: Tools, specifics: dict) -> RoutineResult:
    day = anomaly.date
    base_day = anomaly.comparison_window[0] if anomaly.comparison_window else day
    day_orders = tools.get_orders(day, day)
    base_orders = tools.get_orders(base_day, base_day)
    day_rev = _sku_revenue(day_orders)
    base_rev = _sku_revenue(base_orders)
    gaps = {sku: base_rev.get(sku, 0.0) - day_rev.get(sku, 0.0) for sku in base_rev}
    total_gap = sum(g for g in gaps.values() if g > 0) or 1e-9
    driver = max(gaps, key=lambda s: gaps[s])
    share = gaps[driver] / total_gap
    ev = [Evidence(
        tool="get_orders", args={"day": day, "baseline": base_day},
        result_summary=(
            f"vs {base_day}, '{driver}' lost ${gaps[driver]:.0f} "
            f"= {share*100:.0f}% of the day's revenue gap"
        ),
        supports=share >= 0.5,
    )]
    verdict = Verdict.CONFIRMED if share >= 0.5 else Verdict.REFUTED
    return RoutineResult(
        ev, verdict, min(0.95, 0.5 + share / 2),
        {"driver_sku": driver, "driver_title": _title_for(base_orders, driver),
         "driver_gap": round(gaps[driver], 2), "gap_share": round(share, 2)},
    )


def routine_order_velocity_drop(anomaly: AnomalyEvent, tools: Tools, specifics: dict) -> RoutineResult:
    day = anomaly.date
    base_day = anomaly.comparison_window[0] if anomaly.comparison_window else day
    sku = specifics.get("driver_sku") or specifics.get("stockout_sku")
    if not sku:
        # Pick the day's biggest baseline seller.
        base_orders = tools.get_orders(base_day, base_day)
        rev = _sku_revenue(base_orders)
        sku = max(rev, key=lambda s: rev[s]) if rev else None
    if not sku:
        return RoutineResult([], Verdict.INCONCLUSIVE, 0.0)
    day_units = sum(
        li["quantity"] for o in tools.get_orders(day, day)
        for li in o.get("line_items", []) if li["sku"] == sku
    )
    base_units = sum(
        li["quantity"] for o in tools.get_orders(base_day, base_day)
        for li in o.get("line_items", []) if li["sku"] == sku
    )
    drop = (base_units - day_units) / base_units if base_units else 0.0
    ev = [Evidence(
        tool="get_orders", args={"sku": sku, "day": day, "baseline": base_day},
        result_summary=f"{sku} sold {day_units} units vs {base_units} on {base_day} ({drop*100:.0f}% drop)",
        supports=drop >= 0.3,
    )]
    verdict = Verdict.CONFIRMED if drop >= 0.3 else Verdict.REFUTED
    return RoutineResult(ev, verdict, min(0.9, max(0.2, drop)), {"velocity_sku": sku})


def routine_return_spike(anomaly: AnomalyEvent, tools: Tools, specifics: dict) -> RoutineResult:
    day = anomaly.date
    orders = tools.get_orders(day, day)
    refunds = [o for o in orders if "refund" in str(o.get("financial_status", "")).lower()]
    rate = len(refunds) / len(orders) if orders else 0.0
    ev = [Evidence(
        tool="get_orders", args={"day": day},
        result_summary=f"{len(refunds)}/{len(orders)} orders refunded ({rate*100:.0f}%)",
        supports=rate >= 0.15,
    )]
    verdict = Verdict.CONFIRMED if rate >= 0.15 else Verdict.REFUTED
    return RoutineResult(ev, verdict, 0.6 if rate >= 0.15 else 0.2)


def routine_price_change(anomaly: AnomalyEvent, tools: Tools, specifics: dict) -> RoutineResult:
    day = anomaly.date
    base_day = anomaly.comparison_window[0] if anomaly.comparison_window else day

    def avg_prices(orders):
        acc: dict[str, list] = {}
        for o in orders:
            for li in o.get("line_items", []):
                acc.setdefault(li["sku"], []).append(li.get("price", 0.0))
        return {k: sum(v) / len(v) for k, v in acc.items() if v}

    d, b = avg_prices(tools.get_orders(day, day)), avg_prices(tools.get_orders(base_day, base_day))
    changed = [s for s in d if s in b and abs(d[s] - b[s]) > 0.01 * max(b[s], 1)]
    ev = [Evidence(
        tool="get_orders", args={"day": day, "baseline": base_day},
        result_summary=(f"prices changed for {changed}" if changed else "no SKU price changes vs baseline"),
        supports=bool(changed),
    )]
    verdict = Verdict.CONFIRMED if changed else Verdict.REFUTED
    return RoutineResult(ev, verdict, 0.6 if changed else 0.2)


def routine_fulfillment_delay(anomaly: AnomalyEvent, tools: Tools, specifics: dict) -> RoutineResult:
    # Honest: v1 does not capture fulfillment timestamps, so this cannot be confirmed.
    # The routine still runs (checks we have nothing) and reports the data gap rather
    # than inventing a conclusion.
    ev = [Evidence(
        tool="(none)", args={},
        result_summary="fulfillment timing not captured in v1 — cannot confirm/refute",
        supports=None,
    )]
    return RoutineResult(ev, Verdict.INCONCLUSIVE, 0.0)


ROUTINES = {
    CauseType.STOCKOUT: routine_stockout,
    CauseType.SINGLE_SKU_DRIVER: routine_single_sku_driver,
    CauseType.ORDER_VELOCITY_DROP: routine_order_velocity_drop,
    CauseType.RETURN_SPIKE: routine_return_spike,
    CauseType.PRICE_CHANGE: routine_price_change,
    CauseType.FULFILLMENT_DELAY: routine_fulfillment_delay,
}


def has_routine(cause: CauseType) -> bool:
    return cause in ROUTINES


def find_at_risk_sku(tools: Tools) -> dict | None:
    """For the recommended action: the in-stock SKU closest to its own stockout."""
    best = None
    for lvl in tools.get_inventory_levels():
        avail = lvl["available"]
        if avail <= 0:
            continue
        vel = tools.get_order_velocity(lvl["sku"], window=14)["per_day"]
        if vel <= 0:
            continue
        days = avail / vel
        if best is None or days < best["days"]:
            best = {"sku": lvl["sku"], "title": lvl.get("title", lvl["sku"]),
                    "available": avail, "per_day": vel, "days": round(days, 1)}
    return best

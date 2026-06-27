"""Phase 6 — Streamlit dashboard. Talks to FastAPI over HTTP only (no agent/MCP imports).

    streamlit run scout/dashboard/app.py

Set SCOUT_API_URL to the deployed FastAPI URL (default http://localhost:8000).
"""

from __future__ import annotations

import os

import httpx
import pandas as pd
import streamlit as st

API_URL = os.environ.get("SCOUT_API_URL", "http://localhost:8000")
STORE_ID = os.environ.get("SCOUT_STORE_ID", "demo-store")

st.set_page_config(page_title="Scout", page_icon="🔎", layout="wide")
st.title("🔎 Scout — autonomous data analyst")
st.caption(f"API: {API_URL} · store: {STORE_ID}")


def api_get(path: str, **params):
    r = httpx.get(f"{API_URL}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def api_post(path: str, json: dict):
    r = httpx.post(f"{API_URL}{path}", json=json, timeout=30)
    r.raise_for_status()
    return r.json()


# ── Controls ─────────────────────────────────────────────────────────────────
col_a, col_b = st.columns([1, 4])
with col_a:
    if st.button("▶ Run investigation now", type="primary"):
        try:
            res = api_post("/scout/run", {"store_id": STORE_ID, "force": True})
            st.success(f"Run {res['status']}. Refresh in a few seconds for the finding.")
        except Exception as exc:
            st.error(f"Could not reach API: {exc}")
with col_b:
    st.write("")

# ── Metrics ──────────────────────────────────────────────────────────────────
st.subheader("Revenue vs same-weekday baseline")
try:
    rev = api_get("/metrics/revenue", store_id=STORE_ID)
    df = pd.DataFrame(rev["series"])
    base = pd.DataFrame(rev["baseline"])
    if not df.empty:
        merged = df.merge(base, on="date", how="left").set_index("date")
        st.line_chart(merged[["value", "baseline"]].rename(
            columns={"value": "revenue", "baseline": "same-weekday baseline (median)"}
        ))
    else:
        st.info("No revenue series yet. Seed the demo: python -m scout.capture.seed_demo")

    st.subheader("Current inventory")
    inv = api_get("/metrics/inventory", store_id=STORE_ID)
    inv_df = pd.DataFrame(inv["levels"])
    if not inv_df.empty:
        st.bar_chart(inv_df.set_index("sku")["available"])
    st.caption(
        "Note: Scout does not report a true conversion rate — the Admin API exposes orders, "
        "not sessions. Any volume figure shown is an explicit orders-based proxy."
    )
except Exception as exc:
    st.warning(f"Metrics unavailable (is the API running?): {exc}")

# ── Findings feed ────────────────────────────────────────────────────────────
st.subheader("Findings")
try:
    data = api_get("/findings", store_id=STORE_ID, limit=25)
    findings = data["findings"]
    if not findings:
        st.info("No findings yet. Click 'Run investigation now'.")
    for f in findings:
        with st.container(border=True):
            st.markdown(f"**{f['headline']}**")
            st.markdown(f"**Action:** {f['finding'].get('recommended_action', '')}")
            cause = f["confirmed_cause"] or "inconclusive"
            st.caption(f"{f['created_at']} · cause: {cause} · confidence: {f['confidence']}")
            with st.expander("Evidence"):
                for e in f["finding"].get("evidence", []):
                    mark = {True: "✓", False: "✗", None: "·"}[e.get("supports")]
                    st.write(f"{mark} `{e['tool']}` — {e['result_summary']}")
except Exception as exc:
    st.warning(f"Findings unavailable (is the API running?): {exc}")

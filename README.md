# Scout — autonomous data analyst for Shopify sellers

Scout monitors a Shopify store's metrics, detects **meaningful** anomalies against a
**day-of-week-aware** baseline, autonomously investigates the cause from a fixed taxonomy,
and delivers a plain-English finding with evidence and one recommended action.

> **Example output Scout produces (verified end-to-end on the bundled demo):**
> *Revenue dropped 18% Tuesday vs your last 5 Tuesdays — your top SKU (Black Tee — M) went
> out of stock at 2pm.*
> **Action:** Restock Black Tee — M now, and reorder Grey Tee — M too — it's ~3 days from
> its own stockout at current velocity (3.1/day).

---

## Demo vs live — one switch

Scout runs **today with no Shopify or OpenAI credentials** using an explicit, labeled demo
path. Two env vars flip it to live; there is **no silent mock fallback** — selecting a real
backend without creds fails loudly.

| Switch | Demo (default) | Live |
|---|---|---|
| `SCOUT_DATA_SOURCE` | `demo` (reads the seeded local store) | `shopify` (Admin GraphQL API) |
| `SCOUT_LLM_MODE` | `stub` (deterministic, no key) | `openai` or `azure` |

## Repo layout (frontend / backend split)

```
backend/    FastAPI + agent + MCP server + capture + eval + tests   (the scout package)
frontend/   standalone Streamlit dashboard (HTTP-only; deploys independently)
docker-compose.yml   orchestrates both + Postgres
.env.example         shared config (works from root or backend/)
CLAUDE.md            full build brief; phase0_reconstruct.py is the throwaway probe
```

## Quickstart (demo, ~2 minutes)

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows: .venv\Scripts\activate

# Backend (run these from the backend/ dir)
pip install -e "./backend[all]"
cd backend
python -m scout.capture.seed_demo     # seed ~8 weeks of synthetic data + the incident
python -m scout.agent.run             # detect + investigate -> prints the Finding
python -m eval.run_eval               # precision/recall/attribution (gated)
pytest -q                             # test suite
```

Run the backend API + the frontend dashboard:

```bash
# terminal 1 — backend API
cd backend && uvicorn scout.api.main:app --port 8000

# terminal 2 — frontend dashboard (talks to the API over HTTP)
cd frontend && pip install -r requirements.txt
SCOUT_API_URL=http://localhost:8000 streamlit run app.py     # dashboard at :8501

# or everything at once (api + worker + dashboard + Postgres):
docker compose up --build
```

## Architecture

```
Shopify ──webhooks──▶ /capture (HMAC-verified)         our event store (SQLite/Postgres)
                         orders_create                  ├─ order_snapshots / line_items
                         inventory_levels_update        ├─ inventory_level_events  ◀─ "hit 0 at 2pm"
scheduled backfill ─────────────────────────▶          └─ metric_timeseries (weekday-aware)
                                                                    │
/agent detection (median+MAD, same-weekday) ───────────────────────┘
        │ AnomalyEvent
        ▼
/agent LangGraph: ingest → generate_hypotheses → investigate (governed loop) → synthesize
        │   (agent is an MCP CLIENT)            │
        │                                       ▼  MCP tools over stdio
        └──────────────────────────────▶ /mcp_server  (wraps Shopify Admin GraphQL;
                                            get_inventory_events reads OUR store)
        │ Finding
        ▼
/api (FastAPI) ── persists ──▶ findings ── /dashboard (Streamlit, HTTP only)
        └── notifications: Slack + SendGrid (direct SDK)
```

Key design decisions:
- **Detection is day-of-week aware and robust.** A Tuesday is compared only to the last 5
  Tuesdays via median + MAD (not mean + std). Defaults: `baseline_same_weekdays=5`,
  `robust_z_threshold=3.5`, `min_baseline_history=3`. See `scout/agent/detection.py` for
  the rationale. Verified on demo data: 1 true positive, 0 false positives over 21 days.
- **The agent never calls Shopify directly.** It is an MCP client; the MCP server owns
  auth, rate-limiting, and pagination. `get_inventory_events` reads our captured store —
  point-in-time inventory history the Admin API does not retain.
- **Hypotheses are grounded.** The LLM selects only from a fixed taxonomy
  (`STOCKOUT, RETURN_SPIKE, PRICE_CHANGE, FULFILLMENT_DELAY, ORDER_VELOCITY_DROP,
  SINGLE_SKU_DRIVER`); each maps to an investigation routine. No routine ⇒ not a hypothesis.
- **Governed loop.** Max hypotheses, max iterations/hypothesis, and a per-run token budget;
  the run terminates deterministically even if inconclusive.
- **Conversion is not faked.** The Admin API has no sessions/traffic, so Scout never emits a
  "conversion" number; any volume figure is labeled an orders-based proxy.

## Going live

1. Complete Shopify **Step Zero** (see `CLAUDE.md`): dev store, custom app, Admin API token,
   scopes `read_orders, read_products, read_inventory, read_locations`.
2. `cp .env.example .env` and fill Shopify creds; set `SCOUT_DATA_SOURCE=shopify`.
3. Apply the schema: `alembic upgrade head` (instead of relying on `create_all`).
4. Sync the variant map so inventory webhooks resolve to SKUs:
   `python -m scout.capture.variant_sync`  (re-run when products/variants change)
5. Register webhooks so inventory/order history accumulates:
   `python scripts/register_webhooks.py https://<public-host>/webhooks/shopify`
6. For real findings text set `SCOUT_LLM_MODE=openai` + `OPENAI_API_KEY` (or `azure`).
7. **History takes time.** Detection needs ≥ `min_baseline_history` (3) same-weekdays —
   realistically **4–6 weeks** of capture before same-weekday baselines and inventory-event
   history are meaningful. Start capturing early.

## Why one container for v1 (and when to split)

The image runs the API + in-process queue worker + agent + MCP server (stdio subprocess) +
capture. Split out when you scale: (a) the **queue/worker** to its own process so long
investigations don't block webhook intake; (b) the **MCP server** if you want it
independently deployable/rate-limited; (c) move the DB to managed Postgres. The compose file
already separates the DB and the scheduled backfill worker.

## Deployment

**Frontend — Streamlit Community Cloud (free):** push this repo, point Community Cloud at
`frontend/app.py`, and set `SCOUT_API_URL` to your deployed backend URL. Community Cloud
runs **only** the dashboard — it cannot host the backend (no persistent webhook endpoint,
DB, or scheduler). See `frontend/README.md`.

**Backend — needs a persistent webhook endpoint + DB + a scheduled job.** Three realistic options:

| Option | ~Monthly | DB | Persistent webhook | Scheduled job | Notes |
|---|---|---|---|---|---|
| **Render** (Web Service + Postgres + Cron) | ~$7 web + ~$7 Postgres (+free cron) ≈ **$14** | Managed Postgres add-on | Yes (always-on web service) | Render Cron Job runs `scripts/scheduler.py` | Simplest; Docker-native; good default for v1. |
| **Railway** (service + Postgres plugin) | usage-based, ≈ **$5–20** | Postgres plugin | Yes | Run the worker as a second service | Fast setup; cost scales with usage. |
| **Fly.io** (app + Fly Postgres + machine) | ≈ **$5–15** | Fly Postgres | Yes (always-on machine) | `fly machine`/scheduled run for backfill | Cheapest at small scale; more ops knobs. |

All three handle the three hard requirements (managed Postgres, an always-on HTTPS endpoint
Shopify can POST to, and a scheduled backfill). Pick **Render** if you want the least setup.

## Repo layout

```
frontend/                   Phase 6   — Streamlit dashboard (standalone HTTP client)
backend/
  scout/capture       Phase 0.5 — event store, HMAC webhooks, backfill, demo seeder
  scout/mcp_server    Phase 1   — MCP server (Shopify GraphQL) + demo data source
  scout/agent         Phase 2/3 — detection engine + LangGraph investigation agent
  scout/api           Phase 4   — FastAPI: runs, findings, webhook receiver, debounced queue
  scout/notifications Phase 5   — Slack + SendGrid (direct SDK)
  eval                Phase 3.5 — cassettes + golden cases + metrics
  migrations          Alembic (Postgres-ready)
  scripts             mcp_smoketest, verify_events, register_webhooks, send_test_webhook, scheduler
  tests               detection, HMAC, pipeline, API
phase0_reconstruct.py       throwaway honest-test probe (repo root; not part of the package)
```

See `CLAUDE.md` for the full build brief, Shopify Step Zero, and phase-by-phase intent.

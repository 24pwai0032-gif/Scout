# SCOUT — Build Brief & Phased Prompts

> This file auto-loads every session. It is the source of truth for what Scout is, the
> tech stack, the non-negotiable engineering practices, and the phased build order.
> Build phases in order. Do NOT skip Phase 0 or Phase 0.5 — they are the real risk.

---

## PROJECT BRIEF

You are building **Scout**, an autonomous data analyst for Shopify sellers. Scout is not
a dashboard — it is an agentic system that monitors store metrics, detects *meaningful*
anomalies (not noise), autonomously investigates root causes, and presents a
plain-English finding with evidence and one recommended action.

### Example output Scout must be able to produce
"Revenue dropped 18% Tuesday vs your last four Tuesdays — your top SKU went out of stock
at 2pm; restock it and Grey Tee, which is ~3 days from a stockout at current velocity."

The phrase **"vs your last four Tuesdays"** is the core of why this finding is trustworthy
rather than a false alarm. Detection must be day-of-week aware from day one.

### Core product loop
1. **Monitor** — pull Shopify metrics on a schedule and via webhooks (orders, revenue,
   returns, inventory levels) and persist them as a time series we own.
2. **Detect** — flag statistically meaningful anomalies against a *seasonally-aware*
   baseline (see Detection requirements), not a flat trailing average.
3. **Investigate** — for each anomaly, form hypotheses *drawn from a fixed taxonomy of
   causes the system can actually test*, then query data to confirm or rule each out.
4. **Synthesize** — produce a plain-English finding: what happened, the confirmed cause,
   the supporting evidence (with the like-for-like comparison), and one concrete action.
5. **Deliver** — push to Slack/email and show in the Streamlit dashboard.

### Tech stack (use exactly this — do not substitute libraries without asking)
- **Frontend**: Streamlit
- **Backend API**: FastAPI + Pydantic + Uvicorn
- **Agent orchestration**: LangGraph (LangChain ecosystem)
- **LLM**: OpenAI API (default gpt-4.1 or equivalent; support Azure OpenAI as a swappable
  backend via env config)
- **Data source**: Shopify Admin API (GraphQL preferred), accessed through a **custom MCP
  server** — never via direct SDK calls from the agent (see MCP section)
- **Event capture + storage**: our own database, populated from Shopify webhooks and
  scheduled pulls. This is a first-class component, not an afterthought (see Data section)
- **Notifications (v1)**: direct Slack SDK and SendGrid SDK calls. MCP wrappers for these
  are deferred to v2 — do NOT build them yet.
- **Observability**: LangSmith tracing + Python `logging`
- **Eval**: a deterministic offline eval harness using recorded API fixtures (see Eval)
- **Packaging**: Docker, pushed to Docker Hub
- **Hosting**: Streamlit Community Cloud for the frontend only. The backend (FastAPI +
  agent + MCP server + DB) needs separate hosting — do not assume Community Cloud runs it.

### MCP architecture — read carefully
Scout's LangGraph agent is an **MCP client**. It does NOT call the Shopify Admin API
directly. Instead:
- Build a **custom MCP server** (Python, official `mcp` SDK) wrapping the Shopify Admin
  API (GraphQL preferred).
- Expose MCP tools such as: `get_orders(start_date, end_date)`,
  `get_inventory_levels()`, `get_product_metrics(product_id)`,
  `get_order_velocity(sku, window)`, and — reading from *our own captured event store*,
  not live Shopify — `get_inventory_events(start, end)`.
- The MCP server handles Shopify auth, rate limiting, and pagination internally. These
  concerns must NOT leak into the agent.
- Keep the MCP server an independently runnable process from day one (same container is
  fine initially) — this matters for hosting separation later.

### Data model & data-availability expectations (this is where v1 dies if ignored)
- **Multi-tenant from the start**: `store_id` is a first-class field everywhere, even
  though v1 runs one store.
- **Conversion is NOT freely available.** The Shopify *Admin* API exposes orders, not
  sessions/traffic. You cannot compute true conversion rate from Admin data alone. For
  v1, do ONE of: (a) explicitly define a documented proxy you *can* compute (e.g.
  orders-per-hour, or add-to-cart events if you capture checkout/cart webhooks), and name
  it honestly as a proxy everywhere in the UI and code; or (b) drop conversion from v1
  scope. Do not silently emit a "conversion" number you cannot actually measure.
- **Point-in-time inventory history is NOT freely available.** The Admin API gives
  *current* inventory levels well, but reliable timestamped "this SKU hit zero at 2pm"
  history generally must be **captured by us** by ingesting `inventory_levels/update`
  webhooks into our own store over time. The flagship finding depends on this. Therefore
  the event-capture pipeline (Phase 0.5) must exist and accumulate data before the agent
  can produce the example output. Treat `get_inventory_events()` as reading our captured
  history, not querying Shopify live.
- Use Pydantic models for all API shapes and for internal objects passed between
  LangGraph nodes (Anomaly, Hypothesis, Evidence, Finding).

### Detection requirements (this is the product — do not hand-wave it)
- Baselines must be **day-of-week aware**: compare a metric for a given weekday against
  the trailing distribution of the *same weekday* (e.g. last 4–6 same-weekdays), not a
  flat trailing mean. Comparing a Tuesday to a window that includes weekends produces
  garbage.
- Use a **robust** measure (median + MAD, or similar) rather than mean + std so a single
  prior spike doesn't poison the baseline.
- State explicitly: the baseline window length, the flag threshold, and *why*. Expect to
  tune these against real findings — but ship a defensible default, not a placeholder.
- Require a **minimum baseline history** before flagging (don't fire anomalies when you
  only have 3 days of data). When history is insufficient, say so rather than guessing.
- The flagship is a *revenue* anomaly with a *stockout* cause; make sure detection can
  express that revenue dipped on a like-for-like basis.

### Hypothesis grounding (prevents the agent from inventing untestable causes)
- Hypotheses must be drawn from a **fixed, enumerated taxonomy of causes the MCP tools
  can actually investigate**, e.g.: `STOCKOUT`, `RETURN_SPIKE`, `PRICE_CHANGE`,
  `FULFILLMENT_DELAY`, `ORDER_VELOCITY_DROP`, `SINGLE_SKU_DRIVER`. The LLM ranks/selects
  from this taxonomy and fills in specifics; it does not free-form "maybe a competitor
  ran a sale" that no tool can confirm.
- Each cause type maps to a known investigation routine (which MCP tools to call, what
  evidence confirms/refutes it). If a hypothesis has no investigation routine, it cannot
  be a hypothesis.

### Cost & loop governance (non-negotiable for a webhook-triggered LLM agent)
- **Debounce** investigation triggers: an active store fires order webhooks constantly;
  do not launch a run per webhook. Batch within a window (e.g. coalesce to at most one
  run per store per N minutes).
- **Hard cap** the investigation loop: max hypotheses, max investigation iterations, and
  a per-run token/cost budget. The run must terminate deterministically even if
  inconclusive.
- Investigation runs go through a **queue**, never run synchronously inside a webhook
  handler.

### Non-negotiable engineering practices
- All secrets via environment variables, never hardcoded. Provide `.env.example`.
- Structured logging (not `print`) on every LangGraph node and MCP tool call.
- Every agent run produces a LangSmith trace.
- Write Pydantic schemas before the logic that uses them.
- **No silent mock-data fallbacks in production** — fail loudly and log. (Exception:
  recorded fixtures are explicitly allowed in the *test/eval* path. Production must never
  silently substitute fake data; tests must be deterministic.)
- Verify Shopify webhook **HMAC signatures** on every inbound webhook — reject forgeries.

---

## STEP ZERO — Shopify store & credentials (manual, no code)

Nothing works until there is a real Shopify dev store and a working Admin API token.

1. **Create a development store** via Shopify Partners (partners.shopify.com → Stores →
   Add store → Development store). Free.
2. **Seed it with data.** Products (variants + inventory tracking on) and several test
   orders spread across different days — without a time series, detection has nothing.
3. **Create a custom app and get an Admin API access token** (Settings → Apps and sales
   channels → Develop apps → Create an app → Configure Admin API scopes → Install →
   reveal the Admin API access token).
4. **Grant scopes:** `read_orders`, `read_products`, `read_inventory`, `read_locations`.
5. **Record** (for `.env`, never hardcoded): shop domain, Admin API access token, Admin
   API version.
6. **Sanity check by hand** with curl/REST before any code.

---

## BUILD PHASES (run in order, prove each before moving on)

- **Phase 0 — Manual reconstruction (no repo scaffold).** Throwaway script against the
  real dev store: pull one past day's revenue, the same weekday's revenue for the prior 4
  weeks, current inventory, and that day's order line items. Determine by hand whether
  "revenue down X% vs last 4 same-weekdays" + SKU attribution is reconstructable, and
  document exactly what the Admin API CANNOT give (expect: timestamped inventory history,
  true conversion). Output: a findings note. This determines what Phase 0.5 builds.

- **Phase 0.5 — Event-capture pipeline.** SQLAlchemy schema (SQLite local, Postgres-ready
  via Alembic), `store_id` everywhere: orders snapshot, `inventory_level_events`
  (sku/variant, location, available, timestamp), `metric_timeseries` (store_id, metric,
  weekday-aware timestamp). Webhook intake with HMAC verification persisting
  `inventory_levels/update` and `orders/create`. Scheduled backfill recording daily
  revenue + inventory snapshots. Scripts to register webhooks and verify events land.
  Start accumulating history NOW. State how many days are needed before detection is
  meaningful.

- **Phase 1 — Repo scaffold + Shopify MCP server.** Dirs: `/mcp_server`, `/agent`,
  `/api`, `/dashboard`, `/capture`, `/eval`, `/tests`; root Dockerfile,
  docker-compose.yml, .env.example, dependency manifest. MCP server (GraphQL) tools:
  `get_orders`, `get_inventory_levels`, `get_product_metrics`, `get_order_velocity`, and
  `get_inventory_events` (reads our captured store). Auth/rate-limit/pagination inside the
  server. Standalone test script hitting each tool against the real store.

- **Phase 2 — Detection engine (deterministic, pre-LLM).** Pydantic `AnomalyEvent`.
  Day-of-week-aware, robust (median + MAD) detection with justified window/threshold,
  minimum-history guard. Run against real captured data; inspect false-positive behavior.

- **Phase 3 — LangGraph investigation agent.** MCP *client* (no Shopify SDK here).
  Pydantic `Hypothesis`/`Evidence`/`Finding`. Fixed taxonomy: STOCKOUT, RETURN_SPIKE,
  PRICE_CHANGE, FULFILLMENT_DELAY, ORDER_VELOCITY_DROP, SINGLE_SKU_DRIVER, each with a
  defined investigation routine. Nodes: ingest_anomaly, generate_hypotheses,
  investigate_hypothesis (enforce max hypotheses/iterations/token budget; deterministic
  termination), synthesize_finding. LangSmith + structured logging on every node.

- **Phase 3.5 — Eval harness (`/eval`).** Recorded fixtures ("cassettes") for
  deterministic offline replay. Golden cases: ≥1 true-positive (the Phase 0 stockout day),
  ≥2 true-negatives. Report detection precision/recall, cause-attribution rate,
  false-positive rate. Runnable via `make eval` / single script.

- **Phase 4 — FastAPI backend (governed).** `POST /scout/run`, `GET /findings`, webhook
  receiver (HMAC verify → enqueue debounced run, never synchronous). Persist findings
  (SQLAlchemy, Alembic). Reuse Pydantic models; invoke Phase 3 agent through the queue.

- **Phase 5 — Notifications.** Slack SDK + SendGrid SDK directly (no MCP wrappers).
  Env-configurable. Trigger after a Finding is saved.

- **Phase 6 — Streamlit dashboard.** Findings feed from `/findings`, manual run trigger,
  metric charts (revenue trend with same-weekday baseline overlay, inventory). Label any
  conversion figure explicitly as the defined proxy. Talks to FastAPI over HTTP only.

- **Phase 7 — Docker + deployment.** Dockerfile (one container OK for v1), Streamlit
  Community Cloud note for the frontend pointing at the FastAPI URL, docker-compose for
  full local dev, and 3 realistic backend hosting options with rough monthly cost.

### Sequencing notes
- Run Phase 0 and 0.5 first, for real. If one past incident can't be reconstructed by hand
  from existing data, no agent will.
- Detection (Phase 2) needs tuning once real findings appear; the eval harness (Phase 3.5)
  is how you tune without guessing.
- Phases 5 and 6 can run in parallel once Phase 4 is solid.
- The biggest hidden dependency is *time*: inventory-event history only accumulates after
  Phase 0.5 is live. Start capturing early, even while building later phases.

# Scout — What's Left

_Last updated: 2026-07-01. This file tracks everything still outstanding for the Scout
project. The product is feature-complete and demonstrable end-to-end; what remains is
**deployment/ops**, the unavoidable **time wait** for real data, and **optional polish**._

**Legend** — Owner: 👤 you (account/infra) · 🤖 codeable (I can do) · ⏳ time-gated
Effort: S (minutes) · M (~hour) · L (multi-hour/multi-day)

---

## ✅ Already done (for context)
- Backend: capture pipeline, custom MCP server, day-of-week robust detection, LangGraph
  agent (grounded taxonomy + governance), FastAPI (queue, HMAC webhooks), notifications,
  eval harness, Alembic migration, Docker. **Tests 12/12, eval precision/recall/attribution = 1.0**.
- Live Shopify (`cortexium`) connected; **Phase 0 passed** (all 5 MCP tools work on real data).
- **Real findings** on the actual catalog, written by **Groq** (`llama-3.3-70b-versatile`).
- Two frontends: Streamlit (`frontend/`) and a polished **React app** (`web/`, typecheck + build clean).
- Backend CORS for the browser frontends.
- Everything pushed to GitHub `main` (no secrets, no co-author).

---

## 1. Operational — blocked on your accounts / infra

### 1.1 👤 S — Unlock GitHub billing (CI is red)
- Account disabled for non-payment of **GitHub Pro ($4/mo)**; your Visa ending 1556 declined.
- You ARE a verified student (benefits through Feb 2028), but the paid Pro plan sits on top.
- **Fix:** Settings → Billing → update payment method + pay past-due, then **downgrade to Free**
  (public-repo Actions are free). Or contact GitHub Support to clear the lock as a student.
- Until then, CI won't run; everything is verified locally instead.

### 1.2 👤 M — Deploy the backend (Render)
- Blueprint already committed: [`render.yaml`](render.yaml) (API + scheduled worker + Postgres).
- Steps: dashboard.render.com → **New → Blueprint** → connect repo → fill the 3 secrets
  (`SHOPIFY_STORE_DOMAIN`, `SHOPIFY_ADMIN_TOKEN`, `SHOPIFY_WEBHOOK_SECRET`).
- Tables auto-create on boot. ⚠️ Free tier sleeps → use a paid instance for reliable webhooks.
- For Groq findings in prod: set `SCOUT_LLM_MODE=groq` + `GROQ_API_KEY` in Render env.

### 1.3 👤 M — Deploy the frontend(s)
- **React (`web/`)** → Vercel / Netlify / Cloudflare Pages. Build `npm run build`, output `dist/`.
  Set `VITE_API_URL` to the deployed backend URL and `VITE_STORE_ID`.
- **Streamlit (`frontend/`)** → Streamlit Community Cloud → point at `frontend/app.py`,
  set `SCOUT_API_URL`. (Pick one frontend as primary; React is the richer one.)

### 1.4 👤 M — Turn on webhooks (real data accumulation)
- `variant_sync` already run (inventory_item_id → SKU map populated).
- Needs a public URL Shopify can reach — the deployed backend (1.2) **or** a local tunnel:
  ```
  cd backend && uvicorn scout.api.main:app --port 8000
  cloudflared tunnel --url http://localhost:8000
  python scripts/register_webhooks.py https://<public-url>/webhooks/shopify
  ```
- HMAC verification is already wired (`SHOPIFY_WEBHOOK_SECRET` set). Receive path is tested
  (forged → 401, valid → 200, SKU resolved).
- **Webhooks are forward-only** — Shopify has no "download past history" API; events only
  fire *after* registration. To capture **real** events on demand for a demo: create an
  order + set a product's inventory to 0 in the Shopify admin (fires `orders/create` and
  `inventory_levels/update` instantly). Verify with `python scripts/verify_events.py`.
- Backfill nuance: past **orders/revenue** can be pulled from the Admin API retroactively,
  but **inventory-event history cannot** (Admin API only exposes *current* stock) — that's
  exactly why it must be webhook-captured going forward.

### 1.5 👤 S — Delete Shopify sample products
- The dev store still has Shopify's defaults (snowboards, ski wax, gift cards — mostly no SKU).
- Shopify admin → Products → select them → Bulk actions → Delete. Keep only your 5.
- (Deferred earlier by you.) Cleaner inventory ⇒ cleaner findings.

---

## 2. Time-gated — can't be rushed

### 2.1 ⏳ L — A genuine (non-backdated) flagship finding
- Needs webhooks live (1.4) + **~4–6 weeks** of real orders/inventory + a deliberate stockout
  so same-weekday baselines and timestamped inventory history accumulate.
- The backdated `cortexium-sim` finding proves the system today; this is the real-data version.
- **For a submission/demo (no multi-week wait):** run `python scripts/seed_live_history.py`
  (reads your real catalog, generates 8 weeks of orders + a stockout into the capture DB) →
  produces the flagship finding today. Describe it as simulated *history* over the real store.

### 2.2 ⏳ S→M — Tune detection thresholds against real findings
- Defaults: `SCOUT_BASELINE_SAME_WEEKDAYS=5`, `SCOUT_ROBUST_Z_THRESHOLD=3.5`,
  `SCOUT_MIN_BASELINE_HISTORY=3`. Re-tune once real findings exist, using the eval harness
  (`python -m eval.run_eval`) so changes are measured, not guessed.

---

## 3. Optional code polish

### 3.1 ✅ DONE — `/investigations` backend endpoint (page is now live)
- Added `InvestigationRun` table + migration, run metadata recorded in
  `scout/api/queue.py:run_pipeline` (trigger/status/duration/finding id), `GET /investigations`,
  and `web/src/pages/Investigations.tsx` now fetches it (with mock fallback). Test added.

### 3.2 ✅ DONE — Sign-in screen
- On-brand `/signin` route (`web/src/pages/SignIn.tsx`) + "Sign out" in the sidebar.
  No real auth in v1 — any input continues to the dashboard (labeled as such).

### 3.3 ✅ DONE — Findings use product titles
- Stockout routine resolves the SKU → title (`Black Tee`, not `TEE-BLK-M`) and passes it into
  the finding, so both the template and the LLM use human names.

### 3.4 👤+🤖 S — Notifications (Slack / SendGrid) live test — _still open_
- Code is wired and fails soft. To verify end-to-end, set `SLACK_ENABLED=true` +
  `SLACK_BOT_TOKEN` (and/or `EMAIL_ENABLED=true` + `SENDGRID_API_KEY`) — **needs your keys**.

### 3.5 ✅ DONE — Web app CI
- Added a `web` job to `.github/workflows/ci.yml` (`npm ci` → typecheck → build).
  (Runs once GitHub billing is sorted; the workflow is committed.)

> Also fixed: the eval harness now pins demo/stub env so it's reproducible regardless of a
> local `.env` pointing at a live store.

---

## 4. Deferred to v2 (per the original brief — intentionally out of v1 scope)
- **Conversion proxy** — Admin API has no sessions; currently dropped + labeled. Optionally
  implement a documented orders-per-hour proxy.
- **Returns / fulfillment capture** — the `RETURN_SPIKE` and `FULFILLMENT_DELAY` routines are
  honest-stubs ("cannot confirm — not captured in v1"). Capture those webhooks to enable them.
- **MCP wrappers for Slack/SendGrid** — v1 uses direct SDK calls (brief defers wrappers to v2).
- **True multi-tenant** — `store_id` is everywhere, but only one store is configured/wired.

---

## 5. Security & housekeeping

### 5.1 👤 S — Rotate keys pasted in chat
- During setup, the **Shopify Admin token**, **Shopify API secret**, and **Groq key** were
  pasted into the chat transcript. Low-stakes (dev store), but rotate if you care:
  Shopify app → API credentials (regenerate); console.groq.com (new key). Update local `.env`.
- `.env` is gitignored and was never pushed — verified.

### 5.2 ✅ Resolved (no action)
- `datetime.utcnow()` deprecations → replaced with a naive-UTC helper.
- Web bundle-size warning → fixed via `manualChunks` code-splitting.
- Web tsconfig / `@types/node` IDE errors → fixed with project-references layout.
- CRLF git warnings on Windows → cosmetic only.

---

## Appendix — run it locally

```powershell
# Backend API (demo data, sim store)
cd backend
$env:SCOUT_DATA_SOURCE="demo"; $env:SCOUT_STORE_ID="cortexium-sim"
uvicorn scout.api.main:app --port 8000

# React UI (http://localhost:5173)
cd web && npm install && npm run dev

# Streamlit UI (http://localhost:8501)
cd frontend && pip install -r requirements.txt
$env:SCOUT_API_URL="http://localhost:8000"; $env:SCOUT_STORE_ID="cortexium-sim"
streamlit run app.py

# Re-seed the synthetic-but-real-catalog history any time
cd backend && python scripts/seed_live_history.py        # needs SCOUT_DATA_SOURCE=shopify + creds
```

**Quality gates:** `cd backend && pytest -q` (12/12) · `python -m eval.run_eval` (gated) ·
`cd web && npm run build` (clean).

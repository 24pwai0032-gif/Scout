"""FastAPI app: on-demand runs, findings list, and the HMAC-verified webhook receiver
that ENQUEUES (debounced) rather than running synchronously.

    uvicorn scout.api.main:app --reload
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request, Response
from pydantic import BaseModel

from scout.api.persistence import list_findings
from scout.api.queue import get_queue
from scout.capture.db import init_db
from scout.capture.webhooks import handle_inventory_update, handle_orders_create, verify_hmac
from scout.config import get_settings
from scout.logging_config import configure_logging, get_logger

log = get_logger("scout.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    init_db()
    get_queue().start()
    log.info("api_started", data_source=settings.data_source.value, store_id=settings.store_id)
    yield
    get_queue().stop()


app = FastAPI(title="Scout", version="0.1.0", lifespan=lifespan)


class RunRequest(BaseModel):
    store_id: str | None = None
    force: bool = True  # manual triggers bypass debounce by default


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/scout/run")
def scout_run(body: RunRequest) -> dict:
    settings = get_settings()
    store_id = body.store_id or settings.store_id
    queued = get_queue().enqueue(store_id, reason="manual", force=body.force)
    return {"status": "queued" if queued else "debounced", "store_id": store_id}


@app.get("/findings")
def get_findings(store_id: str | None = None, limit: int = 50) -> dict:
    return {"findings": list_findings(store_id, limit)}


@app.get("/metrics/revenue")
def metrics_revenue(store_id: str | None = None) -> dict:
    from scout.api.metrics import revenue_series

    return revenue_series(store_id or get_settings().store_id)


@app.get("/metrics/inventory")
def metrics_inventory(store_id: str | None = None) -> dict:
    from scout.api.metrics import inventory_levels

    return {"levels": inventory_levels(store_id or get_settings().store_id)}


@app.post("/webhooks/shopify")
async def shopify_webhook(
    request: Request,
    x_shopify_topic: str = Header(default=""),
    x_shopify_hmac_sha256: str = Header(default=""),
    x_shopify_shop_domain: str = Header(default=""),
) -> Response:
    settings = get_settings()
    raw = await request.body()

    if not verify_hmac(settings.shopify_webhook_secret or "", raw, x_shopify_hmac_sha256):
        log.warning("webhook_hmac_rejected", topic=x_shopify_topic, shop=x_shopify_shop_domain)
        return Response(status_code=401, content="invalid HMAC")

    # v1: single store. Multi-tenant: map shop domain -> store_id here.
    store_id = settings.store_id
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return Response(status_code=400, content="invalid JSON")

    if x_shopify_topic == "orders/create":
        handle_orders_create(store_id, payload)
    elif x_shopify_topic == "inventory_levels/update":
        handle_inventory_update(store_id, payload)
    else:
        log.info("webhook_ignored_topic", topic=x_shopify_topic)

    # Never investigate synchronously — enqueue (debounced).
    get_queue().enqueue(store_id, reason=f"webhook:{x_shopify_topic}", force=False)
    return Response(status_code=200, content="ok")

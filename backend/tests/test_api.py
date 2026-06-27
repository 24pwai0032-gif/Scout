import base64
import hashlib
import hmac
import json
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _sign(secret: str, body: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


@pytest.fixture()
def client():
    os.environ["SHOPIFY_WEBHOOK_SECRET"] = "test-secret"
    from scout.config import get_settings

    get_settings.cache_clear()
    from scout.api.main import app

    with TestClient(app) as c:
        yield c


def test_healthz(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_webhook_hmac_accept_and_reject(client):
    body = json.dumps(
        {"id": 1, "created_at": "2026-06-23T15:00:00Z", "total_price": "10.00", "line_items": []}
    ).encode()
    headers = {"Content-Type": "application/json", "X-Shopify-Topic": "orders/create"}

    good = client.post(
        "/webhooks/shopify", content=body,
        headers={**headers, "X-Shopify-Hmac-Sha256": _sign("test-secret", body)},
    )
    assert good.status_code == 200

    bad = client.post(
        "/webhooks/shopify", content=body,
        headers={**headers, "X-Shopify-Hmac-Sha256": "forged"},
    )
    assert bad.status_code == 401


def test_findings_endpoint(client):
    res = client.get("/findings", params={"store_id": "demo-store"})
    assert res.status_code == 200
    assert "findings" in res.json()

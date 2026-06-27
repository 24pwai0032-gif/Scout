"""Test config: use an isolated SQLite db, in-process tools, stub LLM, and seed once."""

from __future__ import annotations

import os

# Pin everything so tests are isolated from any local .env (which may point at a live store).
os.environ["SCOUT_DATABASE_URL"] = "sqlite:///scout_test.db"
os.environ["SCOUT_MCP_TRANSPORT"] = "inprocess"
os.environ["SCOUT_LLM_MODE"] = "stub"
os.environ["SCOUT_DATA_SOURCE"] = "demo"
os.environ["SCOUT_STORE_ID"] = "demo-store"

import pytest

from scout.capture.seed_demo import seed


@pytest.fixture(scope="session", autouse=True)
def _seeded():
    # Fresh DB each run so tests are fully isolated (no leftover rows / unique clashes).
    if os.path.exists("scout_test.db"):
        os.remove("scout_test.db")
    seed("demo-store")
    yield

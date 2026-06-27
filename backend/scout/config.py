"""Central configuration. All secrets/settings come from env (never hardcoded).

`SCOUT_DATA_SOURCE` and `SCOUT_LLM_MODE` are the two switches that let the whole system
run today in `demo`/`stub` mode and flip to real Shopify+OpenAI later by changing env.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> str:
    """Locate .env whether the process runs from the repo root or backend/.

    Checks cwd, then backend/, then the repo root (this file is backend/scout/config.py)."""
    here = Path(__file__).resolve()
    for candidate in (Path.cwd() / ".env", here.parents[1] / ".env", here.parents[2] / ".env"):
        if candidate.exists():
            return str(candidate)
    return ".env"


class DataSource(str, Enum):
    demo = "demo"
    shopify = "shopify"


class LLMMode(str, Enum):
    stub = "stub"
    openai = "openai"
    azure = "azure"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_env_file(), env_file_encoding="utf-8", extra="ignore"
    )

    # Core switches
    data_source: DataSource = Field(default=DataSource.demo, alias="SCOUT_DATA_SOURCE")
    store_id: str = Field(default="demo-store", alias="SCOUT_STORE_ID")
    database_url: str = Field(default="sqlite:///scout.db", alias="SCOUT_DATABASE_URL")

    # Shopify (required only when data_source=shopify)
    shopify_store_domain: str | None = Field(default=None, alias="SHOPIFY_STORE_DOMAIN")
    shopify_admin_token: str | None = Field(default=None, alias="SHOPIFY_ADMIN_TOKEN")
    shopify_api_version: str = Field(default="2026-04", alias="SHOPIFY_API_VERSION")
    shopify_webhook_secret: str | None = Field(default=None, alias="SHOPIFY_WEBHOOK_SECRET")

    # LLM
    llm_mode: LLMMode = Field(default=LLMMode.stub, alias="SCOUT_LLM_MODE")
    llm_model: str = Field(default="gpt-4.1", alias="SCOUT_LLM_MODEL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    azure_openai_endpoint: str | None = Field(default=None, alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: str | None = Field(default=None, alias="AZURE_OPENAI_API_KEY")
    azure_openai_deployment: str | None = Field(default=None, alias="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_version: str = Field(
        default="2024-10-21", alias="AZURE_OPENAI_API_VERSION"
    )

    # Agent governance
    max_hypotheses: int = Field(default=4, alias="SCOUT_MAX_HYPOTHESES")
    max_iters_per_hypothesis: int = Field(default=3, alias="SCOUT_MAX_ITERS_PER_HYPOTHESIS")
    run_token_budget: int = Field(default=20_000, alias="SCOUT_RUN_TOKEN_BUDGET")
    debounce_minutes: int = Field(default=10, alias="SCOUT_DEBOUNCE_MINUTES")

    # Detection
    baseline_same_weekdays: int = Field(default=5, alias="SCOUT_BASELINE_SAME_WEEKDAYS")
    min_baseline_history: int = Field(default=3, alias="SCOUT_MIN_BASELINE_HISTORY")
    robust_z_threshold: float = Field(default=3.5, alias="SCOUT_ROBUST_Z_THRESHOLD")

    # Observability
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_json: bool = Field(default=False, alias="LOG_JSON")

    # Notifications
    slack_enabled: bool = Field(default=False, alias="SLACK_ENABLED")
    slack_bot_token: str | None = Field(default=None, alias="SLACK_BOT_TOKEN")
    slack_channel: str = Field(default="#scout-findings", alias="SLACK_CHANNEL")
    email_enabled: bool = Field(default=False, alias="EMAIL_ENABLED")
    sendgrid_api_key: str | None = Field(default=None, alias="SENDGRID_API_KEY")
    email_from: str | None = Field(default=None, alias="EMAIL_FROM")
    email_to: str | None = Field(default=None, alias="EMAIL_TO")

    def require_shopify(self) -> None:
        """Fail loud if Shopify is selected but not configured (no silent fallback)."""
        if self.data_source is DataSource.shopify:
            missing = [
                name
                for name, val in {
                    "SHOPIFY_STORE_DOMAIN": self.shopify_store_domain,
                    "SHOPIFY_ADMIN_TOKEN": self.shopify_admin_token,
                }.items()
                if not val
            ]
            if missing:
                raise RuntimeError(
                    f"SCOUT_DATA_SOURCE=shopify but missing: {', '.join(missing)}. "
                    "Refusing to run with fake data. Set them or use SCOUT_DATA_SOURCE=demo."
                )

    def require_llm(self) -> None:
        if self.llm_mode is LLMMode.openai and not self.openai_api_key:
            raise RuntimeError("SCOUT_LLM_MODE=openai but OPENAI_API_KEY is unset.")
        if self.llm_mode is LLMMode.azure and not (
            self.azure_openai_endpoint and self.azure_openai_api_key
        ):
            raise RuntimeError("SCOUT_LLM_MODE=azure but Azure endpoint/key unset.")


@lru_cache
def get_settings() -> Settings:
    return Settings()

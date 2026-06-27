"""Shared Pydantic schemas passed between detection, the LangGraph nodes, and the API.

Schemas are defined BEFORE the logic that uses them (per the brief).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from scout.timeutil import utcnow


# ── Detection output ─────────────────────────────────────────────────────────
class AnomalyEvent(BaseModel):
    store_id: str
    metric: str = Field(description="e.g. 'revenue'")
    observed_value: float
    baseline: float = Field(description="robust baseline (median of same-weekdays)")
    deviation_pct: float = Field(description="signed % vs baseline")
    robust_z: float = Field(description="(obs - median) / (1.4826 * MAD)")
    weekday: str = Field(description="e.g. 'Tuesday'")
    comparison_window: list[str] = Field(
        default_factory=list, description="ISO dates of the same-weekdays compared"
    )
    score: float = Field(description="abs(robust_z), higher = stronger anomaly")
    date: str = Field(description="ISO date of the anomalous day")
    detected_at: datetime = Field(default_factory=utcnow)

    def like_for_like(self) -> str:
        direction = "down" if self.deviation_pct < 0 else "up"
        return (
            f"{self.metric.capitalize()} was {direction} "
            f"{abs(self.deviation_pct):.0f}% on {self.weekday} "
            f"vs your last {len(self.comparison_window)} {self.weekday}s"
        )


# ── Hypothesis taxonomy (fixed; the LLM may only select from these) ──────────
class CauseType(str, Enum):
    STOCKOUT = "STOCKOUT"
    RETURN_SPIKE = "RETURN_SPIKE"
    PRICE_CHANGE = "PRICE_CHANGE"
    FULFILLMENT_DELAY = "FULFILLMENT_DELAY"
    ORDER_VELOCITY_DROP = "ORDER_VELOCITY_DROP"
    SINGLE_SKU_DRIVER = "SINGLE_SKU_DRIVER"


class Hypothesis(BaseModel):
    cause_type: CauseType
    rationale: str = Field(description="why this cause is plausible for this anomaly")
    specifics: dict = Field(
        default_factory=dict, description="e.g. {'sku': 'TEE-BLK-M'} to focus the routine"
    )
    rank: int = Field(default=0, description="LLM-assigned priority, lower = first")


class Evidence(BaseModel):
    tool: str = Field(description="MCP tool called")
    args: dict = Field(default_factory=dict)
    result_summary: str
    supports: bool | None = Field(
        default=None, description="True=confirms, False=refutes, None=inconclusive"
    )


class Verdict(str, Enum):
    CONFIRMED = "CONFIRMED"
    REFUTED = "REFUTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class InvestigatedHypothesis(BaseModel):
    hypothesis: Hypothesis
    evidence: list[Evidence] = Field(default_factory=list)
    verdict: Verdict = Verdict.INCONCLUSIVE
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class Finding(BaseModel):
    store_id: str
    headline: str = Field(description="plain-English, includes the like-for-like comparison")
    confirmed_cause: CauseType | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)
    recommended_action: str
    anomaly: AnomalyEvent
    investigated: list[InvestigatedHypothesis] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    llm_mode: str = "stub"
    inconclusive: bool = False

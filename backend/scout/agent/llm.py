"""LLM backends: stub (deterministic, no network), OpenAI, Azure OpenAI.

Two operations the graph needs:
  * rank_hypotheses(anomaly) -> ordered [Hypothesis] selected ONLY from the taxonomy.
  * synthesize(anomaly, investigated, at_risk) -> {headline, recommended_action}.

The stub powers the demo and the eval harness reproducibly. Real backends use structured
output and are constrained to the same enum, so they cannot invent untestable causes.
"""

from __future__ import annotations

from scout.config import LLMMode, Settings, get_settings
from scout.logging_config import get_logger
from scout.models import AnomalyEvent, CauseType, Hypothesis, InvestigatedHypothesis, Verdict

log = get_logger("scout.agent.llm")


class BaseLLM:
    mode = "base"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.tokens_used = 0

    def rank_hypotheses(self, anomaly: AnomalyEvent) -> list[Hypothesis]:  # pragma: no cover
        raise NotImplementedError

    def synthesize(
        self, anomaly: AnomalyEvent, investigated: list[InvestigatedHypothesis], at_risk: dict | None
    ) -> dict:  # pragma: no cover
        raise NotImplementedError


# ── Stub (deterministic) ─────────────────────────────────────────────────────
class StubLLM(BaseLLM):
    mode = "stub"

    def rank_hypotheses(self, anomaly: AnomalyEvent) -> list[Hypothesis]:
        self.tokens_used += 200
        down = anomaly.deviation_pct < 0
        if down:
            order = [
                (CauseType.STOCKOUT, "Revenue drops on a like-for-like weekday often trace to a top SKU going out of stock."),
                (CauseType.SINGLE_SKU_DRIVER, "A concentrated drop suggests one SKU drove most of the gap."),
                (CauseType.ORDER_VELOCITY_DROP, "Fewer units of a key SKU would lower revenue."),
                (CauseType.RETURN_SPIKE, "A burst of refunds could depress net revenue."),
            ]
        else:
            order = [
                (CauseType.SINGLE_SKU_DRIVER, "An upside spike is often one SKU."),
                (CauseType.PRICE_CHANGE, "A price increase can lift revenue at similar volume."),
            ]
        return [
            Hypothesis(cause_type=c, rationale=r, rank=i) for i, (c, r) in enumerate(order)
        ]

    def synthesize(self, anomaly, investigated, at_risk) -> dict:
        self.tokens_used += 400
        return _template_finding(anomaly, investigated, at_risk)


# ── Real backends (OpenAI / Azure) ───────────────────────────────────────────
class OpenAILLM(BaseLLM):
    mode = "openai"

    def _model(self):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=self.settings.llm_model, api_key=self.settings.openai_api_key, temperature=0)

    def rank_hypotheses(self, anomaly: AnomalyEvent) -> list[Hypothesis]:
        return _llm_rank(self._model(), anomaly, self)

    def synthesize(self, anomaly, investigated, at_risk) -> dict:
        return _llm_synthesize(self._model(), anomaly, investigated, at_risk, self)


class AzureLLM(OpenAILLM):
    mode = "azure"

    def _model(self):
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_endpoint=self.settings.azure_openai_endpoint,
            api_key=self.settings.azure_openai_api_key,
            azure_deployment=self.settings.azure_openai_deployment,
            api_version=self.settings.azure_openai_api_version,
            temperature=0,
        )


def _llm_rank(model, anomaly: AnomalyEvent, counter: BaseLLM) -> list[Hypothesis]:
    from langchain_core.messages import HumanMessage, SystemMessage

    causes = ", ".join(c.value for c in CauseType)
    sys = SystemMessage(
        content=(
            "You are Scout's investigator. Select and RANK the 2-4 most plausible causes "
            f"for the anomaly, choosing ONLY from this fixed taxonomy: {causes}. "
            "Return JSON list of {cause_type, rationale}. Do not invent causes outside the list."
        )
    )
    human = HumanMessage(content=anomaly.model_dump_json())
    resp = model.invoke([sys, human])
    counter.tokens_used += _usage(resp)
    import json

    raw = json.loads(_content_json(resp))
    out = []
    for i, item in enumerate(raw):
        try:
            cause = CauseType(item["cause_type"])
        except (KeyError, ValueError):
            continue
        out.append(Hypothesis(cause_type=cause, rationale=item.get("rationale", ""), rank=i))
    return out


def _llm_synthesize(model, anomaly, investigated, at_risk, counter: BaseLLM) -> dict:
    from langchain_core.messages import HumanMessage, SystemMessage

    confirmed = [iv for iv in investigated if iv.verdict == Verdict.CONFIRMED]
    sys = SystemMessage(
        content=(
            "Write a one-sentence plain-English finding for a Shopify seller. MUST include "
            "the like-for-like comparison and exactly one concrete recommended action. "
            "Return JSON {headline, recommended_action}. Use only the supplied evidence."
        )
    )
    payload = {
        "like_for_like": anomaly.like_for_like(),
        "anomaly": anomaly.model_dump(),
        "confirmed": [iv.model_dump() for iv in confirmed],
        "at_risk_sku": at_risk,
    }
    import json

    resp = model.invoke([sys, HumanMessage(content=json.dumps(payload, default=str))])
    counter.tokens_used += _usage(resp)
    data = json.loads(_content_json(resp))
    return {"headline": data["headline"], "recommended_action": data["recommended_action"]}


def _usage(resp) -> int:
    meta = getattr(resp, "usage_metadata", None) or {}
    return int(meta.get("total_tokens", 500))


def _content_json(resp) -> str:
    text = resp.content if isinstance(resp.content, str) else str(resp.content)
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json").strip()
    return text


# ── Shared deterministic templating (used by the stub + as a safety net) ──────
def _template_finding(anomaly: AnomalyEvent, investigated, at_risk) -> dict:
    confirmed = {iv.hypothesis.cause_type: iv for iv in investigated if iv.verdict == Verdict.CONFIRMED}
    weekday, n = anomaly.weekday, len(anomaly.comparison_window)
    drop = abs(anomaly.deviation_pct)

    stock = confirmed.get(CauseType.STOCKOUT)
    driver = confirmed.get(CauseType.SINGLE_SKU_DRIVER)
    title = None
    if driver:
        title = driver.hypothesis.specifics.get("driver_title")
    if stock and not title:
        title = stock.hypothesis.specifics.get("stockout_sku")

    if stock:
        when = stock.hypothesis.specifics.get("stockout_time", "during the day")
        headline = (
            f"Revenue dropped {drop:.0f}% {weekday} vs your last {n} {weekday}s — "
            f"your top SKU ({title}) went out of stock at {when}."
        )
        action = f"Restock {title} now"
        if at_risk:
            action += (
                f", and reorder {at_risk['title']} too — it's ~{at_risk['days']:.0f} days "
                f"from its own stockout at current velocity ({at_risk['per_day']:.1f}/day)"
            )
        return {"headline": headline, "recommended_action": action + "."}

    if driver:
        sku_title = driver.hypothesis.specifics.get("driver_title", "a single SKU")
        headline = (
            f"Revenue moved {anomaly.deviation_pct:.0f}% {weekday} vs your last {n} "
            f"{weekday}s — concentrated in {sku_title}."
        )
        return {"headline": headline, "recommended_action": f"Review {sku_title}'s stock and pricing."}

    # Inconclusive: deterministic low-confidence finding, never a loop.
    headline = (
        f"{anomaly.like_for_like()}, but no single cause from the taxonomy was confirmed."
    )
    return {"headline": headline, "recommended_action": "Review the day's orders and inventory manually."}


def make_llm(settings: Settings | None = None) -> BaseLLM:
    settings = settings or get_settings()
    settings.require_llm()
    if settings.llm_mode is LLMMode.openai:
        log.info("llm_backend", mode="openai", model=settings.llm_model)
        return OpenAILLM(settings)
    if settings.llm_mode is LLMMode.azure:
        log.info("llm_backend", mode="azure")
        return AzureLLM(settings)
    log.info("llm_backend", mode="stub")
    return StubLLM(settings)

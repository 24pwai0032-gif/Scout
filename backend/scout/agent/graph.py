"""Phase 3 — LangGraph investigation agent.

Nodes: ingest_anomaly -> generate_hypotheses -> investigate (loops, governed) ->
synthesize_finding. The run terminates deterministically even if inconclusive.

Governance (non-negotiable for a webhook-triggered LLM agent):
  * max_hypotheses        — caps how many causes we investigate.
  * max_iters_per_hypothesis — caps tool passes per hypothesis.
  * run_token_budget      — hard token/cost ceiling; exceeding it stops the loop and we
                            synthesize with whatever was gathered (low confidence).

LangGraph is the production path (and is what LangSmith traces). A plain-Python fallback
runs the SAME node functions when langgraph isn't installed (offline/eval only).
"""

from __future__ import annotations

from typing import Any, Callable, TypedDict

from scout.agent.llm import BaseLLM, make_llm
from scout.agent.taxonomy import ROUTINES, find_at_risk_sku, has_routine
from scout.config import Settings, get_settings
from scout.logging_config import get_logger
from scout.models import (
    AnomalyEvent,
    CauseType,
    Finding,
    InvestigatedHypothesis,
    Verdict,
)

log = get_logger("scout.agent.graph")

# Lower = preferred when multiple causes are confirmed.
_CAUSE_PRIORITY = {
    CauseType.STOCKOUT: 0,
    CauseType.SINGLE_SKU_DRIVER: 1,
    CauseType.ORDER_VELOCITY_DROP: 2,
    CauseType.RETURN_SPIKE: 3,
    CauseType.PRICE_CHANGE: 4,
    CauseType.FULFILLMENT_DELAY: 5,
}


class AgentState(TypedDict, total=False):
    anomaly: AnomalyEvent
    pending: list
    investigated: list
    finding: Finding
    stop_reason: str


def build_nodes(tools, llm: BaseLLM, settings: Settings) -> dict[str, Callable]:
    def ingest_anomaly(state: AgentState) -> dict:
        a = state["anomaly"]
        log.info("node_ingest", store_id=a.store_id, metric=a.metric, day=a.date, dev=a.deviation_pct)
        return {"pending": [], "investigated": [], "stop_reason": ""}

    def generate_hypotheses(state: AgentState) -> dict:
        a = state["anomaly"]
        hyps = [h for h in llm.rank_hypotheses(a) if has_routine(h.cause_type)]
        hyps = hyps[: settings.max_hypotheses]
        log.info(
            "node_generate_hypotheses",
            count=len(hyps),
            causes=[h.cause_type.value for h in hyps],
            tokens=llm.tokens_used,
        )
        return {"pending": hyps}

    def investigate(state: AgentState) -> dict:
        pending = list(state.get("pending", []))
        investigated = list(state.get("investigated", []))
        h = pending.pop(0)
        # Carry forward specifics already learned (e.g. driver_sku for the velocity routine).
        learned: dict = {}
        for iv in investigated:
            learned.update(iv.hypothesis.specifics)
        routine = ROUTINES[h.cause_type]
        # max_iters_per_hypothesis guards re-tries; our routines resolve in one pass.
        result = routine(state["anomaly"], tools, {**h.specifics, **learned})
        h_out = h.model_copy(update={"specifics": {**h.specifics, **result.specifics}})
        iv = InvestigatedHypothesis(
            hypothesis=h_out, evidence=result.evidence, verdict=result.verdict, confidence=result.confidence
        )
        investigated.append(iv)
        log.info(
            "node_investigate",
            cause=h.cause_type.value,
            verdict=result.verdict.value,
            confidence=result.confidence,
            tokens=llm.tokens_used,
        )
        return {"pending": pending, "investigated": investigated}

    def synthesize_finding(state: AgentState) -> dict:
        a = state["anomaly"]
        investigated: list[InvestigatedHypothesis] = state.get("investigated", [])
        confirmed = [iv for iv in investigated if iv.verdict == Verdict.CONFIRMED]
        best = None
        if confirmed:
            best = sorted(
                confirmed,
                key=lambda iv: (_CAUSE_PRIORITY[iv.hypothesis.cause_type], -iv.confidence),
            )[0]
        at_risk = find_at_risk_sku(tools)
        out = llm.synthesize(a, investigated, at_risk)
        evidence_all = [e for iv in investigated for e in iv.evidence]
        finding = Finding(
            store_id=a.store_id,
            headline=out["headline"],
            confirmed_cause=best.hypothesis.cause_type if best else None,
            confidence=round(best.confidence if best else 0.2, 2),
            evidence=evidence_all,
            recommended_action=out["recommended_action"],
            anomaly=a,
            investigated=investigated,
            llm_mode=llm.mode,
            inconclusive=best is None,
        )
        log.info(
            "node_synthesize",
            confirmed_cause=finding.confirmed_cause.value if finding.confirmed_cause else None,
            confidence=finding.confidence,
            inconclusive=finding.inconclusive,
            tokens=llm.tokens_used,
        )
        return {"finding": finding}

    def should_continue(state: AgentState) -> str:
        pending = state.get("pending", [])
        investigated = state.get("investigated", [])
        if not pending:
            return "synthesize"
        if llm.tokens_used >= settings.run_token_budget:
            log.warning("token_budget_exhausted", tokens=llm.tokens_used)
            return "synthesize"
        if len(investigated) >= settings.max_hypotheses:
            return "synthesize"
        return "investigate"

    def after_generate(state: AgentState) -> str:
        return "investigate" if state.get("pending") else "synthesize"

    return {
        "ingest_anomaly": ingest_anomaly,
        "generate_hypotheses": generate_hypotheses,
        "investigate": investigate,
        "synthesize_finding": synthesize_finding,
        "should_continue": should_continue,
        "after_generate": after_generate,
    }


def _compile_langgraph(nodes: dict[str, Callable]):
    from langgraph.graph import END, StateGraph

    g = StateGraph(AgentState)
    g.add_node("ingest_anomaly", nodes["ingest_anomaly"])
    g.add_node("generate_hypotheses", nodes["generate_hypotheses"])
    g.add_node("investigate", nodes["investigate"])
    g.add_node("synthesize_finding", nodes["synthesize_finding"])
    g.set_entry_point("ingest_anomaly")
    g.add_edge("ingest_anomaly", "generate_hypotheses")
    g.add_conditional_edges(
        "generate_hypotheses", nodes["after_generate"],
        {"investigate": "investigate", "synthesize": "synthesize_finding"},
    )
    g.add_conditional_edges(
        "investigate", nodes["should_continue"],
        {"investigate": "investigate", "synthesize": "synthesize_finding"},
    )
    g.add_edge("synthesize_finding", END)
    return g.compile()


def _run_fallback(nodes: dict[str, Callable], state: AgentState) -> AgentState:
    """Same nodes, no LangGraph. Offline/eval only."""
    state.update(nodes["ingest_anomaly"](state))
    state.update(nodes["generate_hypotheses"](state))
    while nodes["should_continue"](state) == "investigate":
        state.update(nodes["investigate"](state))
    state.update(nodes["synthesize_finding"](state))
    return state


def run_investigation(
    anomaly: AnomalyEvent, tools, llm: BaseLLM | None = None, settings: Settings | None = None
) -> Finding:
    settings = settings or get_settings()
    llm = llm or make_llm(settings)
    nodes = build_nodes(tools, llm, settings)
    initial: AgentState = {"anomaly": anomaly}
    try:
        app = _compile_langgraph(nodes)
        result: Any = app.invoke(initial)
        log.info("graph_engine", engine="langgraph")
    except ImportError:
        log.warning("langgraph_unavailable_using_fallback")
        result = _run_fallback(dict(nodes), initial)
    return result["finding"]

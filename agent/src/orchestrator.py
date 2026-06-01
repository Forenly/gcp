#!/usr/bin/env python3
"""
Multi-agent orchestration layer for the Lawn-Mower Deployment Advisor.

This is the architectural seam where the single-model tool loop in `server.py`
becomes a coordinated team of specialized agents. The current `/recommend`
endpoint drives one Gemini chat that calls every tool itself; that works for a
demo but it's hard to make robust, hard to validate, and easy to let
hallucinate a spec that isn't in the registry.

The decomposition below is a *suggested* starting point, not a finished design.
The agent roles, the message-passing between them, and the safety contract are
deliberately left as stubs so the architecture owner can shape them. Refine,
re-split, or replace any of this — the seam is what matters, not the skeleton.

Suggested roles:
  - RetrieverAgent : owns the MongoDB MCP tools (find_mowers / find_similar_yards
                     / find_plans). Pure grounding — turns a yard spec into
                     candidate facts. No opinions, just retrieval.
  - SelectorAgent  : reasons over the retrieved candidates and picks a primary
                     mower + ranked alternatives, with explicit fit reasons.
  - PlannerAgent   : drafts the deployment plan (dock, boundary, zones, schedule)
                     for the selected mower.
  - SafetyValidator: the guardrail. Every claim that leaves the system must trace
                     back to a row the RetrieverAgent actually returned — no
                     invented model IDs, no specs outside the registry, no
                     sycophantic "sure, that'll work" when the slope exceeds the
                     mower's rated limit. Rejects + asks for a re-pass on failure.

Wiring target: `server.py:get_recommendation` calls `MultiAgentAdvisor.run(yard)`
instead of running the inline chat loop, once this layer is ready.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from mcp_client import (
    tool_find_mowers,
    tool_find_similar_yards,
    tool_find_plans,
    tool_insert_plan,
)


@dataclass
class AdvisorContext:
    """Shared blackboard passed between agents during a single recommendation run."""
    yard: Dict[str, Any]
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    similar_yards: List[Dict[str, Any]] = field(default_factory=list)
    past_plans: List[Dict[str, Any]] = field(default_factory=list)
    selected: Optional[Dict[str, Any]] = None
    alternatives: List[Dict[str, Any]] = field(default_factory=list)
    plan: Optional[Dict[str, Any]] = None
    fit_reasons: List[str] = field(default_factory=list)
    # SafetyValidator writes here; orchestrator reads it to decide on a re-pass.
    violations: List[str] = field(default_factory=list)


class RetrieverAgent:
    """Grounding agent — owns the MCP tools. Facts in, candidates out."""

    def run(self, ctx: AdvisorContext) -> None:
        y = ctx.yard
        ctx.candidates = tool_find_mowers(
            max_area=y.get("area_sqm"),
            max_slope=y.get("slope_pct"),
            boundary_tech=y.get("boundary_type"),
        )
        ctx.similar_yards = tool_find_similar_yards(
            area=y.get("area_sqm"), slope=y.get("slope_pct"), terrain=y.get("terrain")
        )
        yard_ids = [s["_id"] for s in ctx.similar_yards]
        ctx.past_plans = tool_find_plans(yard_ids=yard_ids) if yard_ids else []


class SelectorAgent:
    """Reasoning agent — picks the primary mower + alternatives from candidates."""

    def run(self, ctx: AdvisorContext) -> None:
        # TODO(architecture): replace the naive pick with a Gemini reasoning pass
        # that weighs the candidates against the yard + similar-yard precedents
        # and produces explicit, defensible fit_reasons.
        raise NotImplementedError("SelectorAgent reasoning is the architecture owner's call.")


class PlannerAgent:
    """Planning agent — drafts the deployment plan for the selected mower."""

    def run(self, ctx: AdvisorContext) -> None:
        # TODO(architecture): generate dock location, boundary placement, first-mow
        # zones (with priorities) and a schedule grounded in ctx.past_plans.
        raise NotImplementedError("PlannerAgent generation is the architecture owner's call.")


class SafetyValidator:
    """
    Guardrail agent — the anti-hallucination / anti-sycophancy contract.

    Returns the list of violations (empty == clean). Nothing leaves the system
    that this agent hasn't cleared.
    """

    def check(self, ctx: AdvisorContext) -> List[str]:
        violations: List[str] = []
        candidate_ids = {m["_id"] for m in ctx.candidates}

        if ctx.selected and ctx.selected.get("_id") not in candidate_ids:
            violations.append(
                f"selected mower {ctx.selected.get('_id')!r} was not in the retrieved candidate set"
            )

        # Hard physical contract: never recommend a mower whose rated limits are
        # below the yard's requirements, no matter how confident the reasoner is.
        if ctx.selected:
            if ctx.selected.get("max_yard_area_sqm", 0) < ctx.yard.get("area_sqm", 0):
                violations.append("selected mower's max area is below the yard area")
            if ctx.selected.get("max_slope_pct", 0) < ctx.yard.get("slope_pct", 0):
                violations.append("selected mower's max slope is below the yard slope")

        # TODO(architecture): extend — validate alternatives, plan field coverage,
        # and that every fit_reason cites a retrieved fact.
        return violations


class MultiAgentAdvisor:
    """
    Orchestrates the agent team for one recommendation.

    Flow: retrieve -> select -> plan -> validate (-> re-pass on violation) -> persist.
    The retry/escalation policy on validation failure is intentionally open.
    """

    def __init__(self, max_safety_retries: int = 2) -> None:
        self.retriever = RetrieverAgent()
        self.selector = SelectorAgent()
        self.planner = PlannerAgent()
        self.safety = SafetyValidator()
        self.max_safety_retries = max_safety_retries

    def run(self, yard: Dict[str, Any]) -> Dict[str, Any]:
        ctx = AdvisorContext(yard=yard)
        self.retriever.run(ctx)

        for _ in range(self.max_safety_retries + 1):
            self.selector.run(ctx)
            self.planner.run(ctx)
            ctx.violations = self.safety.check(ctx)
            if not ctx.violations:
                break
            # TODO(architecture): feed ctx.violations back to the Selector/Planner
            # as corrective context for the next pass instead of just retrying.

        if ctx.violations:
            raise RuntimeError(f"advisor failed safety validation: {ctx.violations}")

        trace_id = tool_insert_plan(
            yard_id=ctx.yard.get("_id", "adhoc"),
            mower_id=ctx.selected["_id"],
            fit_reasons=ctx.fit_reasons,
            plan_details=ctx.plan,
        )
        return {
            "recommended_mower": ctx.selected,
            "alternatives": ctx.alternatives,
            "deployment_plan": ctx.plan,
            "trace_id": trace_id,
        }

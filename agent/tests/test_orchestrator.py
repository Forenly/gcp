"""Unit tests for orchestrator.py — the multi-agent seam.

Selector/Planner are intentionally NotImplemented stubs, so these tests pin the
parts with real logic: the SafetyValidator contract (anti-hallucination /
physical-limit guardrails) and the RetrieverAgent grounding flow, with the MCP
tools monkeypatched.
"""
import pytest

import orchestrator
from orchestrator import (
    AdvisorContext, RetrieverAgent, SelectorAgent, PlannerAgent,
    SafetyValidator, MultiAgentAdvisor,
)


YARD = {"_id": "yard-1", "area_sqm": 800, "slope_pct": 20,
        "terrain": "gentle-slope", "boundary_type": "wire"}


def ctx_with(selected=None, candidates=()):
    ctx = AdvisorContext(yard=dict(YARD))
    ctx.candidates = list(candidates)
    ctx.selected = selected
    return ctx


# -------------------------------------------------------- SafetyValidator

def test_safety_clean_pass():
    mower = {"_id": "m1", "max_yard_area_sqm": 1000, "max_slope_pct": 30}
    assert SafetyValidator().check(ctx_with(mower, [mower])) == []


def test_safety_rejects_hallucinated_mower():
    """A selected mower that the retriever never returned must be flagged."""
    ghost = {"_id": "made-up", "max_yard_area_sqm": 9999, "max_slope_pct": 99}
    real = {"_id": "m1", "max_yard_area_sqm": 1000, "max_slope_pct": 30}
    violations = SafetyValidator().check(ctx_with(ghost, [real]))
    assert any("not in the retrieved candidate set" in v for v in violations)


def test_safety_rejects_underpowered_area():
    mower = {"_id": "m1", "max_yard_area_sqm": 500, "max_slope_pct": 30}
    violations = SafetyValidator().check(ctx_with(mower, [mower]))
    assert any("max area is below" in v for v in violations)


def test_safety_rejects_underpowered_slope():
    mower = {"_id": "m1", "max_yard_area_sqm": 1000, "max_slope_pct": 10}
    violations = SafetyValidator().check(ctx_with(mower, [mower]))
    assert any("max slope is below" in v for v in violations)


def test_safety_missing_limits_treated_as_zero():
    """A mower doc with no rated limits must NOT pass the physical contract."""
    mower = {"_id": "m1"}
    violations = SafetyValidator().check(ctx_with(mower, [mower]))
    assert len(violations) == 2


def test_safety_no_selection_is_clean():
    assert SafetyValidator().check(ctx_with(None, [])) == []


# --------------------------------------------------------- RetrieverAgent

def test_retriever_grounds_context(monkeypatch):
    monkeypatch.setattr(orchestrator, "tool_find_mowers",
                        lambda **kw: [{"_id": "m1"}])
    monkeypatch.setattr(orchestrator, "tool_find_similar_yards",
                        lambda **kw: [{"_id": "y1"}, {"_id": "y2"}])
    seen = {}

    def fake_find_plans(yard_ids=None, **_):
        seen["yard_ids"] = yard_ids
        return [{"_id": "p1"}]

    monkeypatch.setattr(orchestrator, "tool_find_plans", fake_find_plans)

    ctx = AdvisorContext(yard=dict(YARD))
    RetrieverAgent().run(ctx)
    assert ctx.candidates == [{"_id": "m1"}]
    assert seen["yard_ids"] == ["y1", "y2"]      # plans looked up via similar yards
    assert ctx.past_plans == [{"_id": "p1"}]


def test_retriever_skips_plans_without_similar_yards(monkeypatch):
    monkeypatch.setattr(orchestrator, "tool_find_mowers", lambda **kw: [])
    monkeypatch.setattr(orchestrator, "tool_find_similar_yards", lambda **kw: [])

    def must_not_call(**_):
        raise AssertionError("find_plans must not run with no yard ids")

    monkeypatch.setattr(orchestrator, "tool_find_plans", must_not_call)
    ctx = AdvisorContext(yard=dict(YARD))
    RetrieverAgent().run(ctx)
    assert ctx.past_plans == []


# ------------------------------------------------------ MultiAgentAdvisor

def test_stub_agents_raise_not_implemented():
    with pytest.raises(NotImplementedError):
        SelectorAgent().run(AdvisorContext(yard=dict(YARD)))
    with pytest.raises(NotImplementedError):
        PlannerAgent().run(AdvisorContext(yard=dict(YARD)))


def test_orchestrator_full_run_with_stubbed_agents(monkeypatch):
    """End-to-end happy path with the stub agents replaced by deterministic ones:
    retrieve → select → plan → validate → persist."""
    mower = {"_id": "m1", "max_yard_area_sqm": 1000, "max_slope_pct": 30}
    monkeypatch.setattr(orchestrator, "tool_find_mowers", lambda **kw: [mower])
    monkeypatch.setattr(orchestrator, "tool_find_similar_yards", lambda **kw: [])
    monkeypatch.setattr(orchestrator, "tool_insert_plan", lambda **kw: "plan-test01")

    adv = MultiAgentAdvisor()

    class Select:
        def run(self, ctx):
            ctx.selected = ctx.candidates[0]
            ctx.fit_reasons = ["fits area and slope"]

    class Plan:
        def run(self, ctx):
            ctx.plan = {"dock_location": "patio", "schedule": "Mon/Fri"}

    adv.selector, adv.planner = Select(), Plan()
    out = adv.run(dict(YARD))
    assert out["recommended_mower"]["_id"] == "m1"
    assert out["trace_id"] == "plan-test01"


def test_orchestrator_raises_after_exhausting_safety_retries(monkeypatch):
    """If every pass keeps violating the physical contract, run() must fail loudly
    rather than ship an unsafe recommendation."""
    weak = {"_id": "m1", "max_yard_area_sqm": 100, "max_slope_pct": 5}
    monkeypatch.setattr(orchestrator, "tool_find_mowers", lambda **kw: [weak])
    monkeypatch.setattr(orchestrator, "tool_find_similar_yards", lambda **kw: [])

    adv = MultiAgentAdvisor(max_safety_retries=1)

    class Select:
        def run(self, ctx):
            ctx.selected = ctx.candidates[0]

    class Plan:
        def run(self, ctx):
            ctx.plan = {}

    adv.selector, adv.planner = Select(), Plan()
    with pytest.raises(RuntimeError, match="safety validation"):
        adv.run(dict(YARD))

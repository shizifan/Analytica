"""Contract: planning_node forwards plan.revision_log entries into
state["degradations"] so the user-facing channel never silently swallows
multi-round fallbacks or partial section failures.

Tested at the planning_node level (not inside graph compilation) so the
unit stays focused on the iterating-and-forwarding logic.
"""
from __future__ import annotations

import pytest

from backend.tools.loader import load_all_tools

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module", autouse=True)
def _ensure_tools_loaded():
    load_all_tools()


def _state_with_intent() -> dict:
    return {
        "structured_intent": {"output_complexity": "full_report"},
        "messages": [],
    }


async def _run_planning_with_revision_log(monkeypatch, revision_entries):
    """Drive planning_node with a stub PlanningEngine.generate_plan that
    returns a plan carrying the given revision_log entries. Returns the
    state dict after planning_node executed."""
    from backend.agent import graph
    from backend.models.schemas import AnalysisPlan, TaskItem

    plan = AnalysisPlan(
        title="t", analysis_goal="g", estimated_duration=10,
        tasks=[TaskItem(task_id="T001", type="data_fetch",
                        tool="tool_api_fetch",
                        params={"endpoint_id": "E"})],
        revision_log=list(revision_entries),
    )

    async def fake_generate_plan(self, *_args, **_kwargs):
        return plan

    monkeypatch.setattr(
        "backend.agent.planning.PlanningEngine.generate_plan",
        fake_generate_plan,
    )
    monkeypatch.setattr(graph, "build_llm", lambda *_a, **_k: object())

    state = _state_with_intent()
    state = await graph.planning_node(state)
    return state


async def test_multi_round_stitch_failure_becomes_degradation_event(monkeypatch):
    state = await _run_planning_with_revision_log(monkeypatch, [
        {
            "phase": "multi_round_stitch",
            "ts": 0,
            "sections_total": 4,
            "sections_kept": 3,
            "failed_sections": [["S2", "TimeoutError('boom')"]],
        },
    ])
    events = state.get("degradations", [])
    assert any(
        e["layer"] == "planning"
        and "多轮规划部分章节失败" in e["reason"]
        and e["affected"]["failed_sections"]
        for e in events
    ), f"expected multi_round_stitch degradation, got {events}"


async def test_multi_round_stitch_no_failures_does_not_emit_event(monkeypatch):
    state = await _run_planning_with_revision_log(monkeypatch, [
        {
            "phase": "multi_round_stitch",
            "ts": 0,
            "sections_total": 4,
            "sections_kept": 4,
            "failed_sections": [],
        },
    ])
    events = state.get("degradations", []) or []
    # No failures → no event (otherwise users get noise on every full_report)
    assert all("多轮规划部分章节失败" not in e["reason"] for e in events)


async def test_multi_round_fallback_becomes_degradation_event(monkeypatch):
    state = await _run_planning_with_revision_log(monkeypatch, [
        {
            "phase": "multi_round_fallback",
            "ts": 0,
            "error_type": "TimeoutError",
            "error": "skeleton timeout",
        },
    ])
    events = state.get("degradations", [])
    assert any(
        e["layer"] == "planning"
        and "多轮规划失败" in e["reason"]
        and e["affected"]["error_type"] == "TimeoutError"
        for e in events
    ), f"expected multi_round_fallback degradation, got {events}"


async def test_validation_drops_still_forwarded(monkeypatch):
    """Regression guard: extending the loop must not break existing
    `validation` phase forwarding."""
    state = await _run_planning_with_revision_log(monkeypatch, [
        {
            "phase": "validation",
            "ts": 0,
            "original_count": 5,
            "kept_count": 3,
            "dropped": {"T004": "hallucinated tool", "T005": "upstream dropped: T004"},
        },
    ])
    events = state.get("degradations", [])
    assert any(
        "规划阶段过滤" in e["reason"] and e["affected"]["dropped"]
        for e in events
    )

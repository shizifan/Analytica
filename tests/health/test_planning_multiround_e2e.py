"""Multi-round planning end-to-end with a mocked LLM.

These tests exercise the full multi-round dispatch path:
  generate_plan → _generate_plan_multiround → skeleton + sections → stitch
without hitting a real LLM. They verify call sequencing, output shape, and
that a skeleton-side failure cleanly falls back to single-round.
"""
from __future__ import annotations

import json

import pytest

from backend.tools.loader import load_all_tools

pytestmark = pytest.mark.health


@pytest.fixture(scope="module", autouse=True)
def _ensure_tools_loaded():
    load_all_tools()


def _skeleton_response() -> str:
    return json.dumps({
        "title": "全港吞吐量月报",
        "analysis_goal": "分析本期吞吐量趋势与同比变化",
        "needs_attribution": True,
        "output_formats": ["HTML"],
        "sections": [
            {"section_id": "S1", "name": "总体概览",
             "description": "聚焦本期吞吐量水平", "domain_hint": "D2",
             "focus_metrics": ["吞吐量"], "expected_task_count": 2},
            {"section_id": "S2", "name": "趋势分析",
             "description": "聚焦同比与月度趋势", "domain_hint": "D2",
             "focus_metrics": ["同比"], "expected_task_count": 2},
        ],
    })


def _section_response(section_id: str) -> str:
    return json.dumps({
        "tasks": [
            {"task_id": f"{section_id}.T1", "type": "data_fetch",
             "name": "拉取吞吐量", "description": "",
             "depends_on": [], "tool": "tool_api_fetch",
             "params": {"endpoint_id": "getThroughputAndTargetThroughputTon"},
             "intent": "", "estimated_seconds": 10},
            {"task_id": f"{section_id}.V1", "type": "visualization",
             "name": "趋势图", "description": "",
             "depends_on": [f"{section_id}.T1"], "tool": "tool_chart_line",
             "params": {"chart_type": "line"},
             "intent": "展示趋势", "estimated_seconds": 5},
        ],
    })


def _full_intent() -> dict:
    return {
        "raw_query": "出一份全港吞吐量月报",
        "slots": {
            "output_complexity": {"value": "full_report"},
            "output_format": {"value": ["HTML"]},
            "time_range": {
                "value": {"start": "2026-04-01", "end": "2026-04-30",
                          "description": "2026年4月"},
            },
        },
    }


async def test_multiround_full_pipeline(monkeypatch):
    """Skeleton call + 2 section calls + stitch produces a complete plan."""
    # Disable template bypass / template hint so the test exercises the LLM path.
    monkeypatch.setattr(
        "backend.agent.planning.ENABLE_TEMPLATE_BYPASS", False,
    )
    monkeypatch.setattr(
        "backend.agent.planning.ENABLE_TEMPLATE_HINT", False,
    )

    from backend.agent.planning import PlanningEngine

    call_log: list[str] = []

    async def fake_invoke(prompt: str) -> str:
        if "数据分析报告策划专家" in prompt:
            call_log.append("skeleton")
            return _skeleton_response()
        if "section_id: S1" in prompt:
            call_log.append("S1")
            return _section_response("S1")
        if "section_id: S2" in prompt:
            call_log.append("S2")
            return _section_response("S2")
        raise AssertionError(f"unexpected prompt: {prompt[:200]}")

    engine = PlanningEngine(llm=object(), llm_timeout=60, max_retries=1)
    engine._invoke_llm = fake_invoke

    plan = await engine.generate_plan(_full_intent())

    # Skeleton + 2 sections
    assert call_log[0] == "skeleton"
    assert set(call_log[1:]) == {"S1", "S2"}

    ids = {t.task_id for t in plan.tasks}
    assert {"S1.T1", "S1.V1", "S2.T1", "S2.V1"}.issubset(ids)
    assert "G_ATTR" in ids
    assert "G_SUM" in ids
    assert "G_REPORT_HTML" in ids

    # Report wiring
    report = next(t for t in plan.tasks if t.task_id == "G_REPORT_HTML")
    assert "G_SUM" in report.depends_on
    assert "S1.V1" in report.depends_on or "S2.V1" in report.depends_on


async def test_multiround_falls_back_when_skeleton_times_out(monkeypatch):
    """Skeleton TimeoutError must fall through to single-round, not bubble up."""
    monkeypatch.setattr(
        "backend.agent.planning.ENABLE_TEMPLATE_BYPASS", False,
    )
    monkeypatch.setattr(
        "backend.agent.planning.ENABLE_TEMPLATE_HINT", False,
    )

    from backend.agent.planning import PlanningEngine

    # Single-round path: pretend the LLM produces a tiny valid plan.
    single_round_response = json.dumps({
        "title": "fallback", "analysis_goal": "fb",
        "estimated_duration": 10,
        "tasks": [
            {"task_id": "T001", "type": "data_fetch",
             "tool": "tool_api_fetch", "depends_on": [],
             "params": {"endpoint_id": "getThroughputAndTargetThroughputTon"},
             "estimated_seconds": 10},
            {"task_id": "T002", "type": "visualization",
             "tool": "tool_chart_line", "depends_on": ["T001"],
             "params": {"chart_type": "line"}, "estimated_seconds": 5},
            {"task_id": "T003", "type": "report_gen",
             "tool": "tool_report_html", "depends_on": ["T002"],
             "params": {"intent": "fb"}, "estimated_seconds": 30},
        ],
    })

    call_log: list[str] = []

    async def fake_invoke(prompt: str) -> str:
        if "数据分析报告策划专家" in prompt:
            call_log.append("skeleton")
            raise TimeoutError("simulated skeleton timeout")
        # All non-skeleton prompts → single-round full plan
        call_log.append("single")
        return single_round_response

    engine = PlanningEngine(llm=object(), llm_timeout=60, max_retries=1)
    engine._invoke_llm = fake_invoke

    plan = await engine.generate_plan(_full_intent())

    assert "skeleton" in call_log
    assert "single" in call_log
    # Single-round plan returned, not a multi-round one
    assert all(not t.task_id.startswith("S1.") for t in plan.tasks)
    assert plan.title == "fallback"

    # Fallback must be recorded so graph.planning_node can surface it as
    # a DegradationEvent — silent fallback is a regression we explicitly
    # want to prevent.
    fb = next(
        (e for e in plan.revision_log if e.get("phase") == "multi_round_fallback"),
        None,
    )
    assert fb is not None, "fallback to single-round was not recorded"
    assert fb["error_type"] == "TimeoutError"
    assert "skeleton timeout" in fb["error"]


async def test_multiround_tolerates_one_section_failure(monkeypatch):
    """If one of two sections raises, stitch still produces a plan but the
    failed section is dropped from report_structure."""
    monkeypatch.setattr(
        "backend.agent.planning.ENABLE_TEMPLATE_BYPASS", False,
    )
    monkeypatch.setattr(
        "backend.agent.planning.ENABLE_TEMPLATE_HINT", False,
    )
    # Skeleton with 4 sections so 1 failure (25%) is under the 40% cap.
    skeleton_4 = json.dumps({
        "title": "t", "analysis_goal": "g",
        "needs_attribution": False, "output_formats": ["HTML"],
        "sections": [
            {"section_id": f"S{i}", "name": f"sec{i}",
             "description": "", "domain_hint": "D2",
             "focus_metrics": [], "expected_task_count": 2}
            for i in range(1, 5)
        ],
    })

    from backend.agent.planning import PlanningEngine

    async def fake_invoke(prompt: str) -> str:
        if "数据分析报告策划专家" in prompt:
            return skeleton_4
        # S2 fails twice (first attempt + retry); others succeed.
        for sid in ("S1", "S3", "S4"):
            if f"section_id: {sid}" in prompt:
                return _section_response(sid)
        raise TimeoutError("simulated S2 failure")

    engine = PlanningEngine(llm=object(), llm_timeout=60, max_retries=1)
    engine._invoke_llm = fake_invoke

    plan = await engine.generate_plan(_full_intent())

    section_names = [s["name"] for s in plan.report_structure["sections"]]
    assert "sec2" not in section_names
    assert {"sec1", "sec3", "sec4"} == set(section_names)

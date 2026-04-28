"""Contract: planning emits a structured span sequence.

The trace pane needs every planning round-trip to be observable:
  - phase span around the whole LLM-driven path
  - planning_skeleton span for round 1
  - one planning_section span per section (concurrent in real runs)
  - planning_stitch span for the deterministic merge
  - planning_single_round span when the request goes / falls back to single-round

These tests use a mocked LLM and capture WS events through ws_ctx so the
sequence + payload shape is pinned independently of the real transport.
"""
from __future__ import annotations

import json

import pytest

from backend.tools.loader import load_all_tools

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module", autouse=True)
def _ensure_tools_loaded():
    load_all_tools()


def _full_intent() -> dict:
    return {
        "raw_query": "出一份全港吞吐量月报",
        "slots": {
            "output_complexity": {"value": "full_report"},
            "output_format": {"value": ["HTML"]},
            "time_range": {
                "value": {
                    "start": "2026-04-01", "end": "2026-04-30",
                    "description": "2026年4月",
                },
            },
        },
    }


def _skeleton_response() -> str:
    return json.dumps({
        "title": "全港吞吐量月报",
        "analysis_goal": "分析趋势",
        "needs_attribution": True,
        "output_formats": ["HTML"],
        "sections": [
            {"section_id": "S1", "name": "概览",
             "description": "", "domain_hint": "D2",
             "focus_metrics": ["吞吐量"], "expected_task_count": 2},
            {"section_id": "S2", "name": "趋势",
             "description": "", "domain_hint": "D2",
             "focus_metrics": ["同比"], "expected_task_count": 2},
        ],
    })


def _section_response(section_id: str) -> str:
    return json.dumps({
        "tasks": [
            {"task_id": f"{section_id}.T1", "type": "data_fetch",
             "tool": "tool_api_fetch",
             "params": {"endpoint_id": "getThroughputAndTargetThroughputTon"},
             "intent": "", "estimated_seconds": 10},
            {"task_id": f"{section_id}.V1", "type": "visualization",
             "tool": "tool_chart_line", "depends_on": [f"{section_id}.T1"],
             "params": {"chart_type": "line"},
             "intent": "趋势", "estimated_seconds": 5},
        ],
    })


@pytest.fixture
def captured_spans(monkeypatch):
    """Capture every {"event":"trace_span", "span":{...}} that flows
    through ws_ctx during the test."""
    from backend.agent import ws_ctx

    captured: list[dict] = []

    async def cb(payload):
        if payload.get("event") == "trace_span":
            captured.append(payload["span"])

    token = ws_ctx.set_ws_callback(cb)
    yield captured
    ws_ctx.reset_ws_callback(token)


async def test_multiround_emits_full_span_sequence(monkeypatch, captured_spans):
    """Skeleton + N section + stitch + outer phase all show up."""
    monkeypatch.setattr("backend.agent.planning.ENABLE_TEMPLATE_BYPASS", False)
    monkeypatch.setattr("backend.agent.planning.ENABLE_TEMPLATE_HINT", False)

    from backend.agent.planning import PlanningEngine

    async def fake_invoke(prompt: str) -> str:
        if "数据分析报告策划专家" in prompt:
            return _skeleton_response()
        for sid in ("S1", "S2"):
            if f"section_id: {sid}" in prompt:
                return _section_response(sid)
        raise AssertionError("unexpected prompt")

    engine = PlanningEngine(llm=object(), llm_timeout=60, max_retries=1)
    engine._invoke_llm = fake_invoke
    await engine.generate_plan(_full_intent())

    types_seen = {s["span_type"] for s in captured_spans}
    assert "phase" in types_seen
    assert "planning_skeleton" in types_seen
    assert "planning_section" in types_seen
    assert "planning_stitch" in types_seen

    # Each span must carry phase="planning" and a non-empty task_name
    for s in captured_spans:
        assert s["phase"] == "planning"
        assert s["task_name"], f"span missing task_name: {s}"

    # Both sections must have their own start+ok pair
    sec_starts = [s for s in captured_spans
                  if s["span_type"] == "planning_section" and s["status"] == "start"]
    sec_ends = [s for s in captured_spans
                if s["span_type"] == "planning_section" and s["status"] == "ok"]
    sec_task_ids = {s["task_id"] for s in sec_starts}
    assert sec_task_ids == {"planning.section.S1", "planning.section.S2"}
    assert len(sec_ends) == 2


async def test_skeleton_failure_emits_error_span_then_falls_back(monkeypatch, captured_spans):
    """Skeleton TimeoutError → planning_skeleton span has status=error;
    outer phase span continues into single-round path with status=ok."""
    monkeypatch.setattr("backend.agent.planning.ENABLE_TEMPLATE_BYPASS", False)
    monkeypatch.setattr("backend.agent.planning.ENABLE_TEMPLATE_HINT", False)

    from backend.agent.planning import PlanningEngine

    single_round_response = json.dumps({
        "title": "fb", "analysis_goal": "fb", "estimated_duration": 10,
        "tasks": [
            {"task_id": "T001", "type": "data_fetch", "tool": "tool_api_fetch",
             "params": {"endpoint_id": "getThroughputAndTargetThroughputTon"},
             "estimated_seconds": 10},
            {"task_id": "T002", "type": "visualization", "tool": "tool_chart_line",
             "depends_on": ["T001"], "params": {"chart_type": "line"},
             "estimated_seconds": 5},
            {"task_id": "T003", "type": "report_gen", "tool": "tool_report_html",
             "depends_on": ["T002"], "params": {"intent": "fb"},
             "estimated_seconds": 30},
        ],
    })

    async def fake_invoke(prompt: str) -> str:
        if "数据分析报告策划专家" in prompt:
            raise TimeoutError("simulated skeleton timeout")
        return single_round_response

    engine = PlanningEngine(llm=object(), llm_timeout=60, max_retries=1)
    engine._invoke_llm = fake_invoke
    await engine.generate_plan(_full_intent())

    skeleton_spans = [s for s in captured_spans if s["span_type"] == "planning_skeleton"]
    assert any(s["status"] == "error" for s in skeleton_spans)

    # After fallback, single-round span fires successfully
    sr_spans = [s for s in captured_spans if s["span_type"] == "planning_single_round"]
    assert sr_spans, "single-round span missing — fallback not traced"
    assert any(s["status"] == "ok" for s in sr_spans)

    # Outer phase span ends in ok (the user did get a plan in the end)
    phase_spans = [s for s in captured_spans if s["span_type"] == "phase"]
    final_phase = next((s for s in reversed(phase_spans) if s["status"] != "start"), None)
    assert final_phase is not None
    assert final_phase["status"] == "ok"
    # phase span output should record fallback mode
    assert final_phase.get("output", {}).get("mode") == "single_round_fallback"


async def test_stitch_span_carries_failed_section_summary(monkeypatch, captured_spans):
    """When sections partially fail, planning_stitch.output mirrors the
    multi_round_stitch revision_log entry — used by trace UI to show
    which sections were dropped."""
    monkeypatch.setattr("backend.agent.planning.ENABLE_TEMPLATE_BYPASS", False)
    monkeypatch.setattr("backend.agent.planning.ENABLE_TEMPLATE_HINT", False)

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
        for sid in ("S1", "S3", "S4"):
            if f"section_id: {sid}" in prompt:
                return _section_response(sid)
        raise TimeoutError("S2 explodes")

    engine = PlanningEngine(llm=object(), llm_timeout=60, max_retries=1)
    engine._invoke_llm = fake_invoke
    await engine.generate_plan(_full_intent())

    stitch_end = next(
        (s for s in captured_spans
         if s["span_type"] == "planning_stitch" and s["status"] == "ok"),
        None,
    )
    assert stitch_end is not None
    out = stitch_end["output"]
    assert out["sections_kept"] == 3
    assert any("S2" in entry[0] for entry in out["failed_sections"])
    assert "G_SUM" not in out["global_tasks"]  # needs_attribution=False, no analysis tasks
    assert "G_REPORT_HTML" in out["global_tasks"]

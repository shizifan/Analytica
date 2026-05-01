"""Cross-cutting invariant: no pipeline layer silently drops data.

This is a regression suite for the bug class that caused multiple rollbacks:
  - planning validator drops a task → orphan downstream → execution fails
  - report collector drops items → report missing chunks
  - chart parser drops axis spec → broken dual-axis charts
  - format_execution_results unknown output_type → empty card

Each fix is also covered by its own targeted unit test in tests/unit/;
this file is the cross-layer "is the principle alive everywhere" check.
"""
from __future__ import annotations

import pytest

from backend.tools.loader import load_all_tools

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module", autouse=True)
def _ensure_tools_loaded():
    load_all_tools()


# ── Validator: cascade drop + revision_log ──────────────────


def test_validator_records_every_drop_in_revision_log():
    from backend.agent.planning import PlanningEngine
    from backend.models.schemas import AnalysisPlan, TaskItem
    from backend.exceptions import PlanningError

    engine = PlanningEngine(llm=None, llm_timeout=10, max_retries=1)
    plan = AnalysisPlan(title="t", analysis_goal="", estimated_duration=10, tasks=[
        TaskItem(task_id="T001", type="data_fetch", tool="tool_DOES_NOT_EXIST",
                 params={"endpoint_id": "E"}, depends_on=[]),
        TaskItem(task_id="T002", type="visualization", tool="tool_chart_bar",
                 params={}, depends_on=["T001"]),
    ])
    with pytest.raises(PlanningError):
        engine._validate_tasks(plan, valid_tools={"tool_chart_bar"},
                               valid_endpoints={"E"}, complexity="chart_text")
    # Both tasks must be recorded — the silent-drop bug would have left
    # T002 without any explanation.
    assert len(plan.revision_log) == 1
    dropped = plan.revision_log[0]["dropped"]
    assert "T001" in dropped, "direct drop missing from log"
    assert "T002" in dropped, "cascade drop missing from log — orphan task bug class"


def test_complexity_constraint_raises_not_silent():
    """When complexity invariant is violated, validator must raise rather
    than return a half-broken plan."""
    from backend.agent.planning import PlanningEngine
    from backend.models.schemas import AnalysisPlan, TaskItem
    from backend.exceptions import PlanningError

    engine = PlanningEngine(llm=None, llm_timeout=10, max_retries=1)
    # simple_table forbids tool_desc_analysis — must raise
    plan = AnalysisPlan(title="t", analysis_goal="", estimated_duration=10, tasks=[
        TaskItem(task_id="T001", type="data_fetch", tool="tool_api_fetch",
                 params={"endpoint_id": "E"}, depends_on=[]),
        TaskItem(task_id="T002", type="analysis", tool="tool_desc_analysis",
                 params={}, depends_on=["T001"]),
    ])
    with pytest.raises(PlanningError, match="禁止"):
        engine._validate_tasks(
            plan,
            valid_tools={"tool_api_fetch", "tool_desc_analysis"},
            valid_endpoints={"E"},
            complexity="simple_table",
        )


def test_chart_text_without_chart_does_not_raise():
    """chart_text no longer requires charts — fetch + desc_analysis is fine."""
    from backend.agent.planning import PlanningEngine
    from backend.models.schemas import AnalysisPlan, TaskItem

    engine = PlanningEngine(llm=None, llm_timeout=10, max_retries=1)
    plan = AnalysisPlan(title="t", analysis_goal="", estimated_duration=10, tasks=[
        TaskItem(task_id="T001", type="data_fetch", tool="tool_api_fetch",
                 params={"endpoint_id": "E"}, depends_on=[]),
        TaskItem(task_id="T002", type="analysis", tool="tool_desc_analysis",
                 params={"data_ref": "T001"}, depends_on=["T001"]),
    ])
    # Must NOT raise: chart_text now allows fetch + desc_analysis without charts
    engine._validate_tasks(
        plan,
        valid_tools={"tool_api_fetch", "tool_desc_analysis"},
        valid_endpoints={"E"},
        complexity="chart_text",
    )
    assert len(plan.tasks) == 2


def test_chart_text_allows_attribution():
    """chart_text now allows attribution analysis (key fix from boundary spec)."""
    from backend.agent.planning import PlanningEngine
    from backend.models.schemas import AnalysisPlan, TaskItem

    engine = PlanningEngine(llm=None, llm_timeout=10, max_retries=1)
    plan = AnalysisPlan(title="t", analysis_goal="", estimated_duration=10, tasks=[
        TaskItem(task_id="T001", type="data_fetch", tool="tool_api_fetch",
                 params={"endpoint_id": "E"}, depends_on=[]),
        TaskItem(task_id="T002", type="analysis", tool="tool_attribution",
                 params={}, depends_on=["T001"]),
    ])
    engine._validate_tasks(
        plan,
        valid_tools={"tool_api_fetch", "tool_attribution"},
        valid_endpoints={"E"},
        complexity="chart_text",
    )
    assert len(plan.tasks) == 2


# ── Collector: no items dropped under partial task_refs ─────


def test_collector_reassigns_unmatched_to_fallback_section():
    from backend.tools.report._content_collector import _associate, NarrativeItem

    sections = [
        {"name": "概览", "task_refs": ["T1"]},
        {"name": "明细", "task_refs": []},
    ]
    items = [
        NarrativeItem(text="a", source_task="T1"),
        NarrativeItem(text="b", source_task="T2"),
        NarrativeItem(text="c", source_task="T3"),
    ]
    degradations: list[dict] = []
    out = _associate(sections, items, degradations=degradations)
    total = sum(len(s.items) for s in out)
    assert total == 3, "items dropped — silent loss in collector"
    assert len(degradations) == 1, "degradation event not recorded"


def test_sanitize_strips_task_refs_to_align_with_prompt():
    """Prompt promises sections only carry `name`. Sanitiser must strip
    LLM-injected `task_refs` so collector goes through the round-robin
    catch-all path."""
    from backend.agent.planning import _sanitize_report_structure

    rs = {"sections": [
        {"name": "A", "task_refs": ["T1"]},
        {"name": "B"},
    ]}
    cleaned = _sanitize_report_structure(rs)
    for s in cleaned["sections"]:
        assert "task_refs" not in s, "task_refs not stripped — LLM-injected refs leak"


# ── Chart parser: list[dict] axis spec normalised ───────────


def test_axis_spec_list_form_supported():
    """LLM may emit left_y as list-of-dict (multi-series). Parser must
    normalise into {label, series:[...]} instead of dropping."""
    from backend.tools.visualization._config_parser import parse_chart_params

    parsed = parse_chart_params({
        "config": {
            "left_y": [
                {"label": "A", "source": "T1", "y_field": "x"},
                {"label": "B", "source": "T2", "y_field": "y"},
            ],
        },
    })
    assert parsed["left_y"] is not None, "axis spec dropped — silent loss in parser"
    assert "series" in parsed["left_y"]
    assert len(parsed["left_y"]["series"]) == 2


# ── Format execution results: unknown types not silent ──────


def test_format_execution_results_handles_unknown_output_type():
    """Unknown output_type must produce a placeholder, not be silently
    skipped."""
    from backend.agent.execution import _format_execution_results
    from backend.tools.base import ToolOutput
    from backend.models.schemas import TaskItem

    tasks = [TaskItem(task_id="T1", type="analysis", tool="tool_x",
                      name="t1", description="", depends_on=[],
                      params={})]
    ctx = {
        "T1": ToolOutput(
            tool_id="tool_x", status="success",
            output_type="some_future_type",  # unknown
            data={"weird": "shape"},
        ),
    }
    parts = _format_execution_results(tasks, ctx, {"T1": "done"})
    # Must produce at least the task name + a degradation marker; never empty.
    assert any("t1" in p for p in parts), "unknown output_type silently dropped"


def test_build_task_results_payload_always_emits_card():
    """Even unknown output_type must produce a task_results entry so the
    chat bubble shows *something* — never silent."""
    from backend.agent.execution import _build_task_results_payload
    from backend.tools.base import ToolOutput
    from backend.models.schemas import TaskItem

    tasks = [TaskItem(task_id="T1", type="analysis", tool="tool_x",
                      name="t1", description="", depends_on=[],
                      params={})]
    ctx = {
        "T1": ToolOutput(
            tool_id="tool_x", status="success",
            output_type="some_future_type", data={"weird": "shape"},
        ),
    }
    out = _build_task_results_payload(tasks, ctx, {"T1": "done"}, artifacts=None)
    assert len(out["tasks"]) == 1, (
        "task with unknown output_type silently skipped from frontend payload"
    )

"""Regression: planning validator must cascade-drop downstream of filtered
tasks, surface drops in revision_log, and enforce complexity invariants
instead of silently producing broken plans.
"""
from __future__ import annotations

import pytest

from backend.agent.planning import PlanningEngine
from backend.exceptions import PlanningError
from backend.models.schemas import AnalysisPlan, TaskItem


def _engine():
    return PlanningEngine(llm=None, llm_timeout=10, max_retries=1)


def _plan(tasks):
    return AnalysisPlan(
        title="t", analysis_goal="g", estimated_duration=10,
        tasks=tasks,
    )


def _task(tid: str, *, tool: str, type: str = "data_fetch", deps=None, params=None):
    return TaskItem(
        task_id=tid, type=type, tool=tool,
        params=params or {}, depends_on=deps or [],
    )


def test_validator_keeps_clean_plan():
    """Sanity: a fully valid plan survives untouched."""
    plan = _plan([
        _task("T001", tool="tool_api_fetch", params={"endpoint_id": "E"}),
        _task("T002", tool="tool_chart_bar", type="visualization",
              deps=["T001"]),
    ])
    out = _engine()._validate_tasks(
        plan, valid_tools={"tool_api_fetch", "tool_chart_bar"},
        valid_endpoints={"E"}, complexity="chart_text",
    )
    assert len(out.tasks) == 2
    assert out.revision_log == []


def test_validator_cascade_drops_orphan_visualization():
    """Bug 2026-04-25: T001 (data) was filtered, leaving orphan T002 (chart).
    Cascade must drop T002 too. With both gone, complexity check raises."""
    plan = _plan([
        _task("T001", tool="tool_NOT_EXIST", params={"endpoint_id": "E"}),
        _task("T002", tool="tool_chart_bar", type="visualization",
              deps=["T001"]),
    ])
    with pytest.raises(PlanningError):
        _engine()._validate_tasks(
            plan, valid_tools={"tool_chart_bar", "tool_api_fetch"},
            valid_endpoints={"E"}, complexity="chart_text",
        )
    # Both tasks recorded in revision_log: one direct, one cascade
    assert len(plan.revision_log) == 1
    dropped = plan.revision_log[0]["dropped"]
    assert "T001" in dropped
    assert "T002" in dropped
    assert "hallucinated tool" in dropped["T001"]
    assert "upstream dropped" in dropped["T002"]


def test_validator_drops_hallucinated_endpoint():
    plan = _plan([
        _task("T001", tool="tool_api_fetch", params={"endpoint_id": "MISSING"}),
        _task("T002", tool="tool_chart_bar", type="visualization",
              deps=["T001"]),
    ])
    with pytest.raises(PlanningError):
        _engine()._validate_tasks(
            plan, valid_tools={"tool_chart_bar", "tool_api_fetch"},
            valid_endpoints={"E"}, complexity="chart_text",
        )
    dropped = plan.revision_log[0]["dropped"]
    assert "hallucinated endpoint" in dropped["T001"]


def test_complexity_chart_text_requires_data_fetch():
    """chart_text without any data_fetch tool → PlanningError."""
    plan = _plan([
        _task("T001", tool="tool_chart_bar", type="visualization"),
    ])
    with pytest.raises(PlanningError, match="数据获取任务"):
        _engine()._validate_tasks(
            plan, valid_tools={"tool_chart_bar"},
            valid_endpoints=set(), complexity="chart_text",
        )


def test_complexity_chart_text_requires_chart_tool():
    """chart_text without any chart tool → PlanningError."""
    plan = _plan([
        _task("T001", tool="tool_api_fetch", params={"endpoint_id": "E"}),
    ])
    with pytest.raises(PlanningError, match="图表工具"):
        _engine()._validate_tasks(
            plan, valid_tools={"tool_api_fetch"},
            valid_endpoints={"E"}, complexity="chart_text",
        )


def test_complexity_full_report_requires_report_gen():
    plan = _plan([
        _task("T001", tool="tool_api_fetch", params={"endpoint_id": "E"}),
        _task("T002", tool="tool_chart_bar", type="visualization",
              deps=["T001"]),
    ])
    with pytest.raises(PlanningError, match="report_gen"):
        _engine()._validate_tasks(
            plan, valid_tools={"tool_api_fetch", "tool_chart_bar"},
            valid_endpoints={"E"}, complexity="full_report",
        )


def test_revision_log_includes_counts():
    """The revision_log entry must include before/after counts so chat
    bubble can show '原 N → 留 M' to the user."""
    plan = _plan([
        _task("T001", tool="tool_NOT_EXIST", params={"endpoint_id": "E"}),
        _task("T002", tool="tool_api_fetch", params={"endpoint_id": "E"}),
        _task("T003", tool="tool_chart_bar", type="visualization", deps=["T002"]),
    ])
    out = _engine()._validate_tasks(
        plan, valid_tools={"tool_api_fetch", "tool_chart_bar"},
        valid_endpoints={"E"}, complexity="chart_text",
    )
    assert len(out.tasks) == 2
    log = out.revision_log[0]
    assert log["original_count"] == 3
    assert log["kept_count"] == 2
    assert "T001" in log["dropped"]

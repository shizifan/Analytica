"""Unit tests for PR-2 planning.py additions (task_id prefix, plan summary, amend plan)."""

import pytest
from backend.models.schemas import TaskItem, AnalysisPlan
from backend.agent.planning import (
    _add_task_id_prefix,
    _build_completed_plan_summary,
    build_amend_plan,
)


class TestAddTaskIdPrefix:
    """Test _add_task_id_prefix for multi-turn task ID isolation."""

    def _make_task(self, task_id, task_type="data_fetch", depends_on=None, **params):
        return TaskItem(
            task_id=task_id,
            type=task_type,
            name=f"Task {task_id}",
            tool=f"tool_{task_type}",
            params=params,
            depends_on=depends_on or [],
        )

    def test_round_0_no_prefix(self):
        tasks = [
            self._make_task("T001"),
            self._make_task("T002", depends_on=["T001"]),
        ]
        result = _add_task_id_prefix(tasks, 0)

        assert result[0].task_id == "T001"
        assert result[1].task_id == "T002"
        assert result[1].depends_on == ["T001"]

    def test_round_1_adds_prefix(self):
        tasks = [
            self._make_task("T001"),
            self._make_task("T002", depends_on=["T001"]),
        ]
        result = _add_task_id_prefix(tasks, 1)

        assert result[0].task_id == "R1_T001"
        assert result[1].task_id == "R1_T002"
        assert result[1].depends_on == ["R1_T001"]

    def test_round_2_prefixes(self):
        tasks = [
            self._make_task("T003", depends_on=["T001", "T002"]),
        ]
        result = _add_task_id_prefix(tasks, 2)

        assert result[0].task_id == "R2_T003"
        assert result[0].depends_on == ["R2_T001", "R2_T002"]

    def test_already_prefixed_not_doubled(self):
        tasks = [
            self._make_task("R1_T001"),
        ]
        result = _add_task_id_prefix(tasks, 2)

        # Already has R1_ prefix → should be updated to R2_
        assert result[0].task_id == "R2_R1_T001"

    def test_negative_turn_no_prefix(self):
        tasks = [self._make_task("T001")]
        result = _add_task_id_prefix(tasks, -1)
        assert result[0].task_id == "T001"


class TestBuildCompletedPlanSummary:
    """Test _build_completed_plan_summary for prompt injection."""

    def test_empty_history(self):
        result = _build_completed_plan_summary([])
        assert "无历史计划" in result

    def test_single_plan(self):
        history = [
            {
                "title": "Q1吞吐量分析",
                "turn_index": 0,
                "tasks": [
                    {
                        "task_id": "T001",
                        "type": "data_fetch",
                        "name": "获取吞吐量数据",
                        "params": {"endpoint_id": "api/throughput"},
                    },
                ],
            }
        ]
        result = _build_completed_plan_summary(history)

        assert "第 0 轮" in result
        assert "Q1吞吐量分析" in result
        assert "T001" in result
        assert "data_fetch" in result
        assert "api/throughput" in result

    def test_multiple_plans(self):
        history = [
            {"title": "Plan A", "turn_index": 0, "tasks": [
                {"task_id": "T001", "type": "data_fetch", "name": "A1",
                 "params": {}},
            ]},
            {"title": "Plan B", "turn_index": 1, "tasks": [
                {"task_id": "T002", "type": "analysis", "name": "B1",
                 "params": {}},
            ]},
        ]
        result = _build_completed_plan_summary(history)

        assert "第 0 轮" in result
        assert "第 1 轮" in result
        assert "Plan A" in result
        assert "Plan B" in result
        assert "T001" in result
        assert "T002" in result


class TestBuildAmendPlan:
    """Test build_amend_plan (planning.py module-level function)."""

    def _make_state(self, plan_version=1):
        return {
            "analysis_plan": {
                "plan_id": "plan-abc",
                "title": "大连港Q1分析",
                "analysis_goal": "分析大连港2026年Q1吞吐量",
                "report_structure": {"sections": [{"name": "摘要"}]},
                "version": plan_version,
            },
            "analysis_history": [
                {
                    "turn": 0,
                    "key_findings": ["Q1吞吐量同比增长15%"],
                    "artifacts": [{"format": "HTML", "artifact_id": "abc-123"}],
                }
            ],
            "turn_index": 0,
        }

    def test_returns_none_for_undetected_format(self):
        state = self._make_state()
        plan = build_amend_plan(state, "hello world no format keyword")
        assert plan is None

    def test_returns_analysis_plan_for_pptx(self):
        state = self._make_state()
        plan = build_amend_plan(state, "再生成一个 PPTX")

        assert plan is not None
        assert isinstance(plan, AnalysisPlan)
        assert plan.turn_index == 1
        assert plan.parent_plan_id == "plan-abc"
        assert len(plan.tasks) == 1
        assert plan.tasks[0].tool == "tool_report_pptx"

    def test_is_replace_true_for_convert(self):
        state = self._make_state()
        plan = build_amend_plan(state, "换成 docx")

        assert plan is not None
        assert plan.tasks[0].params["is_replace"] is True

    def test_multiple_formats_in_message(self):
        state = self._make_state()
        plan = build_amend_plan(state, "生成 pptx 和 word 报告")

        assert plan is not None
        tools = [t.tool for t in plan.tasks]
        assert "tool_report_pptx" in tools
        assert "tool_report_docx" in tools
        assert len(plan.tasks) == 2

    def test_carries_previous_artifacts(self):
        state = self._make_state()
        plan = build_amend_plan(state, "转成 pptx")

        assert plan is not None
        art = plan.tasks[0].params["_previous_artifacts"]
        assert art == [{"format": "HTML", "artifact_id": "abc-123"}]

    def test_carries_previous_findings(self):
        state = self._make_state()
        plan = build_amend_plan(state, "换成 pptx")

        assert plan is not None
        findings = plan.tasks[0].params["_previous_findings"]
        assert "Q1吞吐量同比增长15%" in findings

    def test_depends_on_empty(self):
        state = self._make_state()
        plan = build_amend_plan(state, "再加一个 PPTX")

        assert plan is not None
        for task in plan.tasks:
            assert task.depends_on == [], f"{task.task_id} should have empty depends_on"

    def test_task_id_format(self):
        state = self._make_state()
        plan = build_amend_plan(state, "加一个 DOCX")

        assert plan is not None
        for task in plan.tasks:
            assert task.task_id.startswith("R1_"), f"Expected R1_ prefix, got {task.task_id}"
            assert "REPORT_" in task.task_id

    def test_empty_analysis_history(self):
        state = self._make_state()
        state["analysis_history"] = []
        plan = build_amend_plan(state, "再加一个 PPTX")

        # Format is detected from message, but prev_artifacts/prev_findings
        # come from empty history
        assert plan is not None
        assert plan.tasks[0].params["_previous_artifacts"] == []
        assert plan.tasks[0].params["_previous_findings"] == []

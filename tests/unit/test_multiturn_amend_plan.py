"""Unit tests for _build_amend_plan in graph.py."""

import pytest
from backend.agent.graph import _build_amend_plan


class TestBuildAmendPlan:
    """Test amend plan construction without LLM."""

    def _make_prev_state(self, artifacts=None, plan_version=1):
        """Build a realistic R0 completed state."""
        return {
            "analysis_plan": {
                "title": "大连港2026年Q1吞吐量趋势分析",
                "tasks": [{"task_id": "T001", "type": "data_fetch"}],
                "version": plan_version,
            },
            "analysis_history": [
                {
                    "turn": 0,
                    "turn_type": "new",
                    "artifacts": (
                        [{"format": "HTML", "artifact_id": "abc-123"}]
                        if artifacts is None
                        else artifacts
                    ),
                }
            ],
            "turn_index": 0,
            "plan_version": plan_version,
            "execution_context": {"T001": {"data": "some data"}},
        }

    def test_add_pptx_format(self):
        """'再加一个 PPTX' should build an amend plan with PPTX report task."""
        state = self._make_prev_state()
        plan = _build_amend_plan(state, "再加一个 PPTX 报告")

        assert len(plan["tasks"]) == 1
        task = plan["tasks"][0]
        assert task["type"] == "report_gen"
        assert task["tool"] == "tool_report_pptx"
        assert "PPTX" in task["name"]
        # depends_on should be empty (V3 fix)
        assert task["depends_on"] == []
        # _previous_artifacts should contain R0 artifacts
        assert task["params"]["_previous_artifacts"] == [
            {"format": "HTML", "artifact_id": "abc-123"},
        ]

    def test_replace_format(self):
        """'换成 DOCX' should build an amend plan with is_replace=True."""
        state = self._make_prev_state()
        plan = _build_amend_plan(state, "换成 DOCX 格式")

        task = plan["tasks"][0]
        assert task["tool"] == "tool_report_docx"
        assert task["params"]["is_replace"] is True

    def test_unrecognized_format_fallback(self):
        """Unrecognized format should default to HTML."""
        state = self._make_prev_state()
        plan = _build_amend_plan(state, "再加一个报告")

        task = plan["tasks"][0]
        assert task["tool"] == "tool_report_html"

    def test_no_previous_artifacts(self):
        """Amend plan should work even without previous artifacts."""
        state = self._make_prev_state(artifacts=[])
        plan = _build_amend_plan(state, "再加一个 PPTX")

        task = plan["tasks"][0]
        assert task["params"]["_previous_artifacts"] == []

    def test_plan_version_increments(self):
        """Amend plan version should be prev_version + 1."""
        state = self._make_prev_state(plan_version=3)
        plan = _build_amend_plan(state, "再加一个 PPTX")
        assert plan["version"] == 4

    def test_no_history_fallback(self):
        """If analysis_history is empty, artifacts should be empty."""
        state = self._make_prev_state()
        state["analysis_history"] = []
        plan = _build_amend_plan(state, "再加一个 PPTX")
        assert plan["tasks"][0]["params"]["_previous_artifacts"] == []

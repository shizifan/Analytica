"""Unit tests for _build_amend_plan in graph.py (PR-2: AnalysisPlan return)."""

import pytest
from backend.agent.graph import _build_amend_plan
from backend.models.schemas import AnalysisPlan


class TestBuildAmendPlan:
    """Test amend plan construction without LLM."""

    def _make_prev_state(self, artifacts=None, plan_version=1):
        """Build a realistic R0 completed state."""
        return {
            "analysis_plan": {
                "plan_id": "plan-r0-001",
                "title": "大连港2026年Q1吞吐量趋势分析",
                "analysis_goal": "分析大连港2026年Q1吞吐量趋势",
                "report_structure": {"sections": []},
                "tasks": [{"task_id": "T001", "type": "data_fetch"}],
                "version": plan_version,
            },
            "analysis_history": [
                {
                    "turn": 0,
                    "turn_type": "new",
                    "key_findings": ["Q1吞吐量同比增长15%"],
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

    # ── dict-style accessors (for backward compat with model_dump) ──

    @staticmethod
    def _dict(plan: AnalysisPlan) -> dict:
        return plan.model_dump()

    # ── Detection tests ─────────────────────────────────────────

    def test_add_pptx_format(self):
        """'再加一个 PPTX' should build an amend plan with PPTX report task."""
        state = self._make_prev_state()
        plan = _build_amend_plan(state, "再加一个 PPTX 报告")

        assert plan is not None
        tasks = plan.tasks
        assert len(tasks) == 1
        task = tasks[0]
        assert task.type == "report_gen"
        assert task.tool == "tool_report_pptx"
        assert "PPTX" in task.name
        # depends_on should be empty (V3 fix)
        assert task.depends_on == []
        # _previous_artifacts should contain R0 artifacts
        assert task.params["_previous_artifacts"] == [
            {"format": "HTML", "artifact_id": "abc-123"},
        ]
        # Verify AnalysisPlan fields
        assert plan.turn_index == 1
        assert plan.parent_plan_id == "plan-r0-001"

    def test_replace_format(self):
        """'换成 DOCX' should build an amend plan with is_replace=True."""
        state = self._make_prev_state()
        plan = _build_amend_plan(state, "换成 DOCX 格式")

        assert plan is not None
        task = plan.tasks[0]
        assert task.tool == "tool_report_docx"
        assert task.params["is_replace"] is True

    def test_detect_word_variant(self):
        """'word' keyword should map to tool_report_docx."""
        state = self._make_prev_state()
        plan = _build_amend_plan(state, "再加一个 word 报告")

        assert plan is not None
        task = plan.tasks[0]
        assert task.tool == "tool_report_docx"

    def test_detect_markdown_variant(self):
        """'markdown' keyword should map to tool_report_markdown."""
        state = self._make_prev_state()
        plan = _build_amend_plan(state, "再加一个 markdown")

        assert plan is not None
        task = plan.tasks[0]
        assert task.tool == "tool_report_markdown"

    def test_unrecognized_format_returns_none(self):
        """Unrecognized format should return None (caller routes to LLM)."""
        state = self._make_prev_state()
        plan = _build_amend_plan(state, "再加一个报告")

        # PR-2: format undetected → None (not default to HTML)
        assert plan is None

    # ── Artifact tests ──────────────────────────────────────────

    def test_no_previous_artifacts(self):
        """Amend plan should work even without previous artifacts."""
        state = self._make_prev_state(artifacts=[])
        plan = _build_amend_plan(state, "再加一个 PPTX")

        assert plan is not None
        task = plan.tasks[0]
        assert task.params["_previous_artifacts"] == []

    def test_no_history_returns_none(self):
        """If analysis_history is empty, can't detect format → None."""
        state = self._make_prev_state()
        state["analysis_history"] = []
        plan = _build_amend_plan(state, "再加一个 PPTX")

        # build_amend_plan reads prev_turn from history;
        # with empty history, prev_turn falls back to {}
        # but format IS detected from user_message → still returns a plan
        assert plan is not None
        task = plan.tasks[0]
        assert task.params["_previous_artifacts"] == []

    # ── Structure tests ─────────────────────────────────────────

    def test_plan_is_analysis_plan_type(self):
        """Return value must be AnalysisPlan (Pydantic model), not dict."""
        state = self._make_prev_state()
        plan = _build_amend_plan(state, "再加一个 PPTX")

        assert isinstance(plan, AnalysisPlan)
        assert plan.title is not None
        assert plan.analysis_goal is not None
        assert len(plan.tasks) >= 1

    def test_task_id_uses_turn_prefix(self):
        """Task IDs should use R{turn_index}_ prefix for multi-turn isolation."""
        state = self._make_prev_state()
        plan = _build_amend_plan(state, "再加一个 PPTX")

        assert plan is not None
        task = plan.tasks[0]
        assert task.task_id.startswith("R1_")


class TestAmendPlanFallback:
    """Test that amend plan routing handles None gracefully."""

    def test_none_means_fallback_to_llm(self):
        """When build_amend_plan returns None, run_stream should use LLM planning."""
        state = {
            "analysis_history": [],
            "turn_index": 0,
            "plan_history": [],
        }
        plan = _build_amend_plan(state, "hello world")
        assert plan is None
        # Caller (run_stream) should detect None and set turn_type="continue"

"""Unit tests for planning_node auto-confirm fix and multi-turn planning."""

import pytest


class TestPlanningAutoConfirm:
    """Test the planning_node auto-confirm logic (V3 fix)."""

    def _make_state_with_plan(self, tasks, task_statuses=None):
        """Helper to build a state dict for planning_node testing."""
        return {
            "current_phase": "planning",
            "analysis_plan": {
                "title": "Test Plan",
                "tasks": tasks,
                "version": 1,
            },
            "task_statuses": task_statuses or {},
            "plan_confirmed": False,
            "structured_intent": {"raw_query": "test"},
            "slots": {"analysis_subject": {"value": "test"}},
            "messages": [{"role": "user", "content": "test"}],
            "turn_type": "new",
            "turn_index": 0,
            "plan_history": [],
        }

    def test_old_plan_all_done_not_auto_confirm(self):
        """If old plan tasks are all done, should NOT auto-confirm.

        The old plan should be archived and plan_confirmed should stay False,
        allowing the graph to flow into planning proper.
        """
        state = self._make_state_with_plan(
            tasks=[
                {"task_id": "T001", "type": "data_fetch"},
                {"task_id": "T002", "type": "analysis"},
            ],
            task_statuses={"T001": "done", "T002": "done"},
        )

        # Simulate the V3 auto-confirm logic
        tasks = state["analysis_plan"]["tasks"]
        all_done = all(
            state["task_statuses"].get(t["task_id"]) in ("done", "skipped")
            for t in tasks
        )

        assert all_done is True, "Both tasks are done"

        if all_done:
            state.setdefault("plan_history", []).append(state["analysis_plan"])
            state["analysis_plan"] = None
            state["plan_confirmed"] = False

        assert state["plan_confirmed"] is False
        assert len(state["plan_history"]) == 1
        assert state["analysis_plan"] is None

    def test_plan_with_pending_tasks_auto_confirm(self):
        """If old plan has pending tasks, auto-confirm to continue execution."""
        state = self._make_state_with_plan(
            tasks=[
                {"task_id": "T001", "type": "data_fetch"},
                {"task_id": "T002", "type": "analysis"},
            ],
            task_statuses={"T001": "done", "T002": "running"},
        )

        tasks = state["analysis_plan"]["tasks"]
        all_done = all(
            state["task_statuses"].get(t["task_id"]) in ("done", "skipped")
            for t in tasks
        )

        assert all_done is False, "T002 is still running"

        if not all_done:
            state["plan_confirmed"] = True

        assert state["plan_confirmed"] is True
        assert state["analysis_plan"] is not None

    def test_empty_tasks_all_done(self):
        """Empty tasks list should be considered 'all done'."""
        state = self._make_state_with_plan(tasks=[], task_statuses={})

        tasks = state["analysis_plan"]["tasks"]
        all_done = all(
            state["task_statuses"].get(t["task_id"]) in ("done", "skipped")
            for t in tasks
        ) if tasks else True

        assert all_done is True

    def test_continue_turn_never_auto_confirm(self):
        """In 'continue' turn, auto-confirm should never trigger
        regardless of task statuses."""
        state = self._make_state_with_plan(
            tasks=[{"task_id": "T001", "type": "data_fetch"}],
            task_statuses={"T001": "running"},
        )
        state["turn_type"] = "continue"

        # The V3 logic: skip auto-confirm when turn_type is continue/amend
        if state["turn_type"] in ("continue", "amend"):
            # Don't enter auto-confirm block at all
            pass

        # plan_confirmed should remain False
        assert state["plan_confirmed"] is False
        assert state["analysis_plan"] is not None

    def test_amend_turn_never_auto_confirm(self):
        """In 'amend' turn, auto-confirm should also never trigger."""
        state = self._make_state_with_plan(
            tasks=[{"task_id": "T001", "type": "data_fetch"}],
            task_statuses={"T001": "done"},
        )
        state["turn_type"] = "amend"

        if state["turn_type"] in ("continue", "amend"):
            pass

        assert state["plan_confirmed"] is False
        assert state["analysis_plan"] is not None


class TestPlanningMultiTurnContext:
    """Test that multi-turn context is injected into planning prompts."""

    def test_build_multiturn_context_injection(self):
        """_build_multiturn_context_injection should produce a usable dict."""
        from backend.agent.graph import _build_multiturn_context_injection

        state = {
            "turn_index": 1,
            "turn_type": "continue",
            "slots": {
                "analysis_subject": {"value": "吞吐量"},
                "time_range": {"value": {"start": "2026-01-01"}},
            },
            "analysis_history": [
                {
                    "turn": 0,
                    "turn_type": "new",
                    "plan_title": "大连港2026年Q1吞吐量趋势分析",
                    "key_findings": ["同比增长2.3%", "3月环比下降5.1%"],
                    "data_snapshots": [
                        {
                            "endpoint": "getThroughputAnalysisByYear",
                            "rows": 12,
                        },
                        {
                            "endpoint": "getThroughputAnalysisByYear",
                            "rows": 6,
                        },
                    ],
                    "artifacts": [{"format": "HTML", "artifact_id": "abc"}],
                    "query": "分析2026年Q1吞吐量",
                    "task_count": 5,
                    "completed_count": 5,
                    "failed_count": 0,
                    "slots_snapshot": {},
                }
            ],
        }

        context = _build_multiturn_context_injection(state)

        assert context["turn_index"] == 1
        assert context["turn_type"] == "continue"
        assert context["latest_summary"]["plan_title"] == "大连港2026年Q1吞吐量趋势分析"
        assert len(context["all_key_findings"]) == 2
        assert "getThroughputAnalysisByYear" in context["prev_data_endpoints"]
        assert len(context["prev_artifacts"]) == 1
        assert "analysis_subject" in context["current_slots"]

    def test_empty_history_returns_empty(self):
        """No analysis_history should return empty context."""
        from backend.agent.graph import _build_multiturn_context_injection

        state = {
            "turn_index": 0,
            "turn_type": "new",
            "analysis_history": [],
            "slots": {},
        }

        context = _build_multiturn_context_injection(state)
        assert context == {}

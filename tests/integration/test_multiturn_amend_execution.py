"""Integration tests for amend fast path in multi-turn conversations.

Verifies that ``build_amend_plan()`` (from ``planning.py``) correctly
detects format-change requests, builds plans with ``depends_on=[]``,
and carries forward previous turn's artifacts and findings.
"""

from __future__ import annotations

import pytest

from backend.memory.store import MemoryStore
from backend.agent.planning import build_amend_plan

pytestmark = pytest.mark.slow


class TestAmendExecution:
    """Verify amend plan builder works correctly with DB-loaded state."""

    async def test_amend_generates_report_without_data_refetch(
        self, multiturn_db_state, test_db_session,
    ):
        """'加一个 PPTX 报告' produces correct plan: depends_on=[], carries artifacts."""
        store = MemoryStore(test_db_session)
        session_data = await store.get_session(multiturn_db_state)
        state = session_data["state_json"]

        plan = build_amend_plan(state, "加一个 PPTX 报告")
        assert plan is not None, "Should return a valid AnalysisPlan"
        assert len(plan.tasks) == 1
        task = plan.tasks[0]
        assert task.tool == "tool_report_pptx"
        assert task.depends_on == [], (
            "amend plan must NOT depend on previous turn task_ids"
        )

        # Verify params carry previous artifacts
        prev_artifacts = task.params.get("_previous_artifacts", [])
        assert len(prev_artifacts) > 0, "Should carry previous artifacts"
        assert prev_artifacts[0]["format"] == "HTML"

    async def test_amend_replace_does_not_duplicate(
        self, multiturn_db_state, test_db_session,
    ):
        """'换成 PPTX 格式' sets is_replace=True, generates only target format."""
        store = MemoryStore(test_db_session)
        session_data = await store.get_session(multiturn_db_state)
        state = session_data["state_json"]

        plan = build_amend_plan(state, "换成 PPTX 格式")
        assert plan is not None
        task = plan.tasks[0]
        assert task.tool == "tool_report_pptx"
        assert task.params.get("is_replace") is True, (
            "is_replace should be True for '换成' messages"
        )

    async def test_amend_carries_previous_findings(
        self, multiturn_db_state, test_db_session,
    ):
        """Amend task params include _previous_findings from analysis_history."""
        store = MemoryStore(test_db_session)
        session_data = await store.get_session(multiturn_db_state)
        state = session_data["state_json"]

        plan = build_amend_plan(state, "再加一个 Word 报告")
        assert plan is not None
        task = plan.tasks[0]

        prev_findings = task.params.get("_previous_findings", [])
        assert len(prev_findings) > 0
        assert any(
            "同比增长" in f for f in prev_findings
        ), "Should contain R0 key findings"

    async def test_unrecognized_format_returns_none(
        self, multiturn_db_state, test_db_session,
    ):
        """Message with no format keyword returns None (caller must fallback to LLM)."""
        store = MemoryStore(test_db_session)
        session_data = await store.get_session(multiturn_db_state)
        state = session_data["state_json"]

        plan = build_amend_plan(state, "hello world no format keyword")
        assert plan is None, (
            "Unrecognized format should return None for LLM fallback"
        )

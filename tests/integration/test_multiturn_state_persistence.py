"""Integration tests for multi-turn state persistence through MySQL.

Verifies that the multi-turn state fields (``turn_index``, ``turn_type``,
``analysis_history``, etc.) survive JSON round-trips through the DB.
"""

from __future__ import annotations

import pytest

from backend.memory.store import MemoryStore

pytestmark = pytest.mark.slow


class TestStatePersistence:
    """Verify multi-turn state persists and reloads correctly."""

    async def test_r0_state_roundtrips_correctly(
        self, multiturn_db_state, test_db_session,
    ):
        """R0 state written to DB → loaded back → all critical fields intact."""
        store = MemoryStore(test_db_session)
        session_data = await store.get_session(multiturn_db_state)
        state = session_data.get("state_json", {})

        assert state["turn_index"] == 0
        assert state["turn_type"] == "new"
        assert len(state["analysis_history"]) == 1
        assert state["analysis_history"][0]["turn"] == 0
        assert len(state["analysis_history"][0]["data_snapshots"]) == 1

        # key_findings survived the JSON round-trip
        findings = state["analysis_history"][0]["key_findings"]
        assert len(findings) == 1
        assert "同比增长" in findings[0]

        # slots present
        assert "analysis_subject" in state["slots"]

        # tasks in analysis_plan
        tasks = state["analysis_plan"]["tasks"]
        assert len(tasks) == 3

    async def test_r1_state_appended_to_history(
        self, multiturn_db_state, test_db_session,
    ):
        """After appending R1 summary, analysis_history has 2 entries."""
        store = MemoryStore(test_db_session)

        # Load R0
        session_data = await store.get_session(multiturn_db_state)
        state = session_data["state_json"]

        # Simulate R1 execution result being appended
        r1_summary = {
            "turn": 1,
            "turn_type": "continue",
            "query": "按港区拆分",
            "data_snapshots": [],
            "key_findings": ["大窑湾港区占比最高，达45%"],
            "artifacts": [],
            "task_count": 3,
            "completed_count": 3,
            "failed_count": 0,
        }
        history = state.get("analysis_history", [])
        history.append(r1_summary)
        state["analysis_history"] = history
        state["turn_index"] = 1

        await store.save_session_state(multiturn_db_state, state)

        # Reload and verify
        session_data2 = await store.get_session(multiturn_db_state)
        state2 = session_data2["state_json"]
        assert len(state2["analysis_history"]) == 2
        assert state2["analysis_history"][1]["turn"] == 1
        assert state2["turn_index"] == 1
        assert "大窑湾" in state2["analysis_history"][1]["key_findings"][0]

    async def test_save_session_state_roundtrip(
        self, multiturn_db_state, test_db_session,
    ):
        """Basic save → load round-trip preserves top-level keys."""
        store = MemoryStore(test_db_session)
        session_data = await store.get_session(multiturn_db_state)
        state = session_data["state_json"]

        expected_keys = [
            "turn_index", "turn_type", "slots",
            "analysis_plan", "task_statuses",
            "analysis_history", "messages", "plan_history",
        ]
        for key in expected_keys:
            assert key in state, f"Missing key: {key}"

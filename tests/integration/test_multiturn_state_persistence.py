"""Integration tests for multi-turn state persistence through MySQL.

Verifies that the multi-turn state fields (``turn_index``, ``turn_type``,
``analysis_history``, etc.) survive JSON round-trips through the DB,
plus the defensive NaN/Inf stripping that keeps MySQL's strict JSON
column from rejecting tool outputs that produced non-finite floats.
"""

from __future__ import annotations

import math

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

    async def test_save_state_strips_nan_and_infinity(
        self, multiturn_db_state, test_db_session,
    ):
        """Regression: a tool output containing ``NaN`` / ``Infinity``
        must not break ``save_session_state``.

        Before the fix, MySQL rejected the JSON payload with
        ER_INVALID_JSON_TEXT (3140) because Python's default
        ``json.dumps`` emits the bare ``NaN`` token. Now the store
        sanitises non-finite floats to ``None`` so the rest of the
        multi-turn context still persists.
        """
        store = MemoryStore(test_db_session)
        session_data = await store.get_session(multiturn_db_state)
        state = session_data["state_json"]

        # Inject the same shape the waterfall tool produced in the
        # production stack-trace that motivated this fix.
        state["execution_context"] = {
            "T_WATERFALL": {
                "metadata": {
                    "yoy_growth": float("nan"),
                    "ratio": float("inf"),
                    "neg_ratio": float("-inf"),
                    "rows": 12,
                },
            },
        }
        state.setdefault("analysis_history", []).append({
            "turn": 99,
            "key_findings": ["NaN regression sample"],
            "stat": float("nan"),
        })

        # Must not raise — sanitiser swaps NaN/Inf for None on the way out.
        await store.save_session_state(multiturn_db_state, state)

        reloaded = await store.get_session(multiturn_db_state)
        meta = reloaded["state_json"]["execution_context"]["T_WATERFALL"]["metadata"]
        assert meta["yoy_growth"] is None
        assert meta["ratio"] is None
        assert meta["neg_ratio"] is None
        assert meta["rows"] == 12  # finite values untouched

        last_turn = reloaded["state_json"]["analysis_history"][-1]
        assert last_turn["turn"] == 99
        assert last_turn["stat"] is None
        # And the JSON round-trip didn't reintroduce non-finites.
        for v in (meta.get("yoy_growth"), meta.get("ratio"),
                  meta.get("neg_ratio"), last_turn.get("stat")):
            assert v is None or (isinstance(v, float) and math.isfinite(v))

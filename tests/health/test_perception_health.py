"""Perception layer minimum sanity check.

Uses the `recorded_llm` fixture (record/replay) so the test exercises the
real LLM behaviour for slot extraction without paying for an LLM call on
every CI run.

To refresh cache: `pytest tests/health/test_perception_health.py --llm-mode=record-missing`
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.health


@pytest.mark.llm_replay
async def test_perception_runs_with_minimal_state(recorded_llm, test_db_session):
    """Perception node accepts a state with raw_query and returns a state
    with structured_intent populated.

    Wiring proven:
      - `build_llm` patched and reachable from `run_perception`
      - DB session usable
      - LLM ainvoke goes through cache
    """
    from backend.agent.perception import run_perception

    state = {
        "messages": [{"role": "user", "content": "查 2026 年集装箱吞吐量"}],
        "raw_query": "查 2026 年集装箱吞吐量",
        "session_id": "perception-health-1",
        "user_id": "perception_health",
    }
    out = await run_perception(state)
    intent = out.get("structured_intent")
    assert intent is not None, "perception did not produce structured_intent"
    assert "slots" in intent, "structured_intent missing slots field"


def test_slot_filling_engine_constructs():
    """SlotFillingEngine instantiates without error (catches import drift)."""
    from backend.agent.perception import SlotFillingEngine
    engine = SlotFillingEngine(llm=None)
    assert engine is not None

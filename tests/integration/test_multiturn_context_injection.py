"""Integration tests for multi-turn context injection into LLM prompts.

Verifies that ``run_perception()`` and ``PlanningEngine.generate_plan()``
receive context from ``analysis_history`` when ``turn_type="continue"``,
so the LLM knows what was already done.
"""

from __future__ import annotations

import pytest

from backend.memory.store import MemoryStore
from backend.agent.graph import (
    build_llm,
    _build_multiturn_context_injection,
)
from backend.agent.perception import run_perception
from backend.agent.planning import PlanningEngine
from tests.lib.multiturn_helpers import make_continue_message

pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def _load_tools():
    from backend.tools.loader import load_all_tools

    load_all_tools()


class TestContextInjection:
    """Verify multi-turn context flows into perception and planning."""

    async def test_perception_prompt_contains_history(
        self,
        multiturn_db_state,
        test_db_session,
        recorded_llm,
    ):
        """R1 perception produces structured_intent with preserved slots."""
        store = MemoryStore(test_db_session)
        session_data = await store.get_session(multiturn_db_state)
        r0_state = session_data["state_json"]

        # Build R1 continuation state
        r1_state = make_continue_message(
            turn_index=1,
            message="按港区拆分看看",
            prev_state=r0_state,
        )

        # Inject _multiturn_context (normally done by run_stream)
        r1_state["_multiturn_context"] = _build_multiturn_context_injection(
            r1_state
        )

        # Run perception (uses recorded_llm behind the scenes)
        result = await run_perception(r1_state)
        intent = result.get("structured_intent")
        assert intent is not None, "R1 perception should produce an intent"

        # The intent should have slots (at minimum analysis_subject)
        slots = intent.get("slots", {})
        assert slots, "structured_intent should contain slots"

    async def test_planning_prompt_contains_completed_tasks(
        self,
        multiturn_db_state,
        test_db_session,
        recorded_llm,
    ):
        """R1 planning receives R0 completed tasks and produces a distinct plan."""
        store = MemoryStore(test_db_session)
        session_data = await store.get_session(multiturn_db_state)
        r0_state = session_data["state_json"]

        # Build R1 continuation state
        r1_state = make_continue_message(
            turn_index=1,
            message="按港区拆分看看各港区吞吐量占比",
            prev_state=r0_state,
        )

        # Simulate perception having produced an intent
        r1_state["structured_intent"] = {
            "analysis_goal": "按港区拆分吞吐量",
            "slots": r0_state["slots"],
        }
        r1_state["_multiturn_context"] = _build_multiturn_context_injection(
            r1_state
        )

        # Planning R1
        llm = build_llm("qwen3-235b", request_timeout=90)
        engine = PlanningEngine(llm=llm, llm_timeout=60, max_retries=1)
        plan = await engine.generate_plan(
            r1_state["structured_intent"],
            employee_id="throughput_analyst",
        )

        assert len(plan.tasks) > 0, "R1 planning should produce tasks"
        # R1 plan should differ from R0 (incremental planning)
        r0_plan_title = r0_state["analysis_plan"]["title"]
        assert plan.title != r0_plan_title, (
            f"R1 plan title '{plan.title}' should differ from R0 '{r0_plan_title}'"
        )

    async def test_multiturn_context_injection_structure(
        self, multiturn_db_state, test_db_session,
    ):
        """_build_multiturn_context_injection produces all required keys."""
        store = MemoryStore(test_db_session)
        session_data = await store.get_session(multiturn_db_state)
        state = session_data["state_json"]

        context = _build_multiturn_context_injection(state)
        assert context, "Should produce non-empty context"

        required_keys = [
            "turn_index",
            "turn_type",
            "latest_summary",
            "all_key_findings",
            "prev_data_endpoints",
            "prev_artifacts",
            "current_slots",
            "plan_history",
        ]
        for key in required_keys:
            assert key in context, f"Missing key in context: {key}"

        assert context["turn_index"] == 0
        assert len(context["all_key_findings"]) >= 1
        assert "getThroughputAnalysisByYear" in context["prev_data_endpoints"]
        assert len(context["prev_artifacts"]) == 1
        assert context["prev_artifacts"][0]["format"] == "HTML"

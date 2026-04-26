"""Full-chain wiring check (perception + planning) via recorded LLM.

Cross-layer health: catches wiring breaks the per-layer health tests
miss — e.g., perception's StructuredIntent shape divergent from what
planning expects.

Marked `health` (not a separate `smoke` tier) so it joins the default
regression run. Refresh cache: `--llm-mode=record-missing`.
"""
from __future__ import annotations

import pytest

from backend.tools.loader import load_all_tools

pytestmark = pytest.mark.health


@pytest.fixture(scope="module", autouse=True)
def _load_tools():
    load_all_tools()


async def test_perception_then_planning_via_recorded_llm(
    recorded_llm, test_db_session,
):
    """A user query → perception (LLM) → planning (LLM) → non-empty plan.

    Catches: LLM client wiring broken, perception output incompatible with
    planning input, planning prompt schema regression.
    """
    from backend.agent.perception import run_perception
    from backend.agent.planning import PlanningEngine
    from backend.agent.graph import build_llm  # patched by recorded_llm fixture

    state = {
        "messages": [{"role": "user", "content": "查 2026 年集装箱吞吐量"}],
        "raw_query": "查 2026 年集装箱吞吐量",
        "session_id": "full-chain-1",
        "user_id": "full_chain",
    }
    state = await run_perception(state)
    intent = state.get("structured_intent")
    assert intent and intent.get("slots"), "perception produced no intent"

    llm = build_llm("qwen3-235b", request_timeout=90)
    engine = PlanningEngine(llm=llm, llm_timeout=60.0, max_retries=2)
    plan = await engine.generate_plan(intent)
    assert plan.tasks, "planning produced empty plan"

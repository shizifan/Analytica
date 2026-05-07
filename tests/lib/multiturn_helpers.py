"""Multi-turn conversation test helpers.

Simulate the state mutations that ``run_stream`` performs in its
continuation branch without spinning up the full WebSocket + graph
pipeline. Useful for integration tests that build a continuation
state from DB-loaded data.

V6: ``make_amend_state`` was deleted along with the keyword-driven
amend fast path (spec §5.6). Amend turns now flow through the same
continuation state shape as continue turns; perception's
MULTITURN_INTENT_PROMPT classifies the intent.
"""

from __future__ import annotations


def make_continue_message(
    turn_index: int, message: str, prev_state: dict
) -> dict:
    """Simulate a continuation turn in unit/integration tests.

    Does NOT call run_stream — just constructs the state the way
    run_stream's continuation branch does (V6 §4.3 + §7.2.1).

    Args:
        turn_index: The new turn number (typically prev_turn + 1).
        message:   The user's follow-up message.
        prev_state: The state dict from the previous turn.

    Returns:
        A new state dict ready to feed into ``run_perception()``,
        ``PlanningEngine.generate_plan()``, etc.
    """
    state = dict(prev_state)
    state["messages"] = list(prev_state.get("messages", []))
    state["messages"].append({"role": "user", "content": message})
    # V6 — turn_type is filled in by perception's multi-turn LLM
    # router; tests that need a specific value override after this.
    state["turn_type"] = None
    state["turn_index"] = turn_index
    state["structured_intent"] = None
    state["current_target_slot"] = None
    state["current_phase"] = "perception"
    state["error"] = None
    state["task_statuses"] = {}
    state["plan_confirmed"] = False

    # Archive the old analysis_plan into plan_history (V6 §7.2.1).
    state.setdefault("plan_history", [])
    if state.get("analysis_plan"):
        state["plan_history"].append(state.pop("analysis_plan"))

    return state

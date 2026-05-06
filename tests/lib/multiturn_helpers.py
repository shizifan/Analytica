"""Multi-turn conversation test helpers.

Simulate the state mutations that ``run_stream`` performs in its
``continue`` and ``amend`` branches, without calling the full
WebSocket + graph pipeline.  Useful for integration tests that
need to construct a continuation state from DB-loaded data.
"""

from __future__ import annotations


def make_continue_message(
    turn_index: int, message: str, prev_state: dict
) -> dict:
    """Simulate a continuation turn in unit/integration tests.

    Does NOT call run_stream — just constructs the state the way
    run_stream would after classification + state continuation
    (``graph.py`` lines 1037-1053).

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
    state["turn_type"] = "continue"
    state["turn_index"] = turn_index
    state["structured_intent"] = None
    state["current_target_slot"] = None
    state["current_phase"] = "perception"
    state["error"] = None
    state["task_statuses"] = {}  # clean previous turn statuses
    state["plan_confirmed"] = False

    # Archive the old analysis_plan into plan_history
    state.setdefault("plan_history", [])
    if state.get("analysis_plan"):
        state["plan_history"].append(state.pop("analysis_plan"))

    return state


def make_amend_state(
    turn_index: int, message: str, prev_state: dict
) -> dict:
    """Simulate an amend turn in unit/integration tests.

    Mirrors the head of the ``amend`` branch in run_stream
    (``graph.py`` lines 976-989), *without* building the
    amend plan or jumping into execution.  Caller should
    invoke ``build_amend_plan()`` / ``_build_amend_plan()``
    separately to inspect the generated plan.

    Args:
        turn_index: The new turn number.
        message:   The user's amend-style message.
        prev_state: The state dict from the previous turn.

    Returns:
        A new state dict with ``turn_type="amend"`` and the
        message appended.
    """
    state = dict(prev_state)
    state["messages"] = list(prev_state.get("messages", []))
    state["messages"].append({"role": "user", "content": message})
    state["turn_type"] = "amend"
    state["turn_index"] = turn_index
    state["current_phase"] = "execution"
    state["task_statuses"] = {}
    return state

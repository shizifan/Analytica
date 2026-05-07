"""Multi-turn conversation test helpers.

Simulate the state mutations that ``run_stream`` performs in its
continuation branch without spinning up the full WebSocket + graph
pipeline. Useful for integration tests that build a continuation
state from DB-loaded data.

V6 helpers added (S5):
  * ``make_task``       — build a TaskItem with sensible defaults
  * ``seed_workspace``  — pre-populate a SessionWorkspace with named
                          payloads (DataFrame / str / dict / bytes)
  * ``consume_run_stream`` — drive run_stream to completion and return
                          the collected event list (for end-to-end
                          tests that need the full graph pipeline)

V6 deletion (spec §5.6):
  * ``make_amend_state`` was removed along with the keyword-driven
    amend fast path; amend turns now share the continuation shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


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


# ── V6 §10.2 — workspace-driven test helpers (S5) ────────────

def make_task(
    task_id: str,
    *,
    type: str = "data_fetch",
    tool: str = "tool_api_fetch",
    depends_on: list[str] | None = None,
    name: str = "",
    params: dict[str, Any] | None = None,
):
    """Build a ``TaskItem`` with V6-friendly defaults. Lazy-imports
    ``backend.models.schemas`` so this module can be imported without
    fully loading the backend (e.g. probe-only test runs)."""
    from backend.models.schemas import TaskItem

    return TaskItem(
        task_id=task_id,
        type=type,  # type: ignore[arg-type]
        tool=tool,
        depends_on=depends_on or [],
        name=name,
        params=params or {},
    )


def seed_workspace(
    root: Path,
    *,
    session_id: str = "s1",
    items: dict[str, Any] | None = None,
    finalize: bool = True,
):
    """Pre-populate a ``SessionWorkspace`` with the given items.

    Each entry is persisted as turn_index=0 with status="success" so
    cross-turn ``data_ref`` resolution can pick them up. If
    ``finalize=True`` (default) the turn_status flips to ``finalized``
    so the planner sees them as durable products.
    """
    from backend.memory.session_workspace import SessionWorkspace
    from backend.tools.base import ToolOutput

    ws = SessionWorkspace(session_id, root)
    for task_id, payload in (items or {}).items():
        ws.persist(
            make_task(task_id),
            ToolOutput(
                tool_id="seed", status="success", output_type="json",
                data=payload,
            ),
            turn_index=0,
        )
    if finalize:
        ws.finalize_turn(0)
    return ws


async def consume_run_stream(
    session_id: str,
    user_id: str,
    message: str,
    *,
    employee_id: str | None = None,
    web_search_enabled: bool = False,
) -> list[Any]:
    """Drive ``backend.agent.graph.run_stream`` to completion and
    return the collected event list.

    Tests that monkeypatch ``perception._call_multiturn_intent_llm``
    or the planner's LLM can use this to exercise the full pipeline
    without depending on a recorded LLM cache.
    """
    from backend.agent.graph import run_stream

    events: list[Any] = []
    async for ev in run_stream(
        session_id=session_id,
        user_id=user_id,
        user_message=message,
        employee_id=employee_id,
        web_search_enabled=web_search_enabled,
    ):
        events.append(ev)
    return events

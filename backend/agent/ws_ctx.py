"""Agent-side WebSocket callback context.

Uses `contextvars.ContextVar` to propagate the per-request WS callback
down through LangGraph nodes without threading it through `state`. This
avoids two problems with the state-based approach:

  1. LangGraph may (now or in future versions) filter state keys against
     the declared `TypedDict` — a non-declared `_ws_callback` could be
     silently dropped.
  2. A callable in state pollutes `json.dumps` at persist time; we had to
     remember to `pop()` it before serialisation.

Consumers:
  - `backend.agent.graph.run_stream` sets/resets around `graph.astream()`.
  - `backend.agent.execution._execute_single_task` reads it when emitting
    `tool_call_start / tool_call_end`.
  - Perception and reflection nodes can read it to emit richer thinking
    events as work progresses.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Optional

WsCallback = Callable[[dict], Awaitable[Any]]

_current_ws_callback: ContextVar[Optional[WsCallback]] = ContextVar(
    "analytica_ws_callback",
    default=None,
)


def set_ws_callback(cb: Optional[WsCallback]):
    """Set the current callback and return a token for later reset."""
    return _current_ws_callback.set(cb)


def reset_ws_callback(token) -> None:
    _current_ws_callback.reset(token)


def get_ws_callback() -> Optional[WsCallback]:
    return _current_ws_callback.get()


async def emit(payload: dict) -> None:
    """Emit a payload via the current callback, if any. Silently drops
    exceptions — observability must not break graph execution."""
    cb = _current_ws_callback.get()
    if cb is None:
        return
    try:
        await cb(payload)
    except Exception:
        # Intentionally swallow — the callback is UI-facing, not critical.
        pass

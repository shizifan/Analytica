"""Lightweight span instrumentation for API and LLM call tracing.

Spans are emitted via an async callable (span_emit) that is created per-task
in execution.py and threaded through SkillInput. Each span is:
  - broadcast over WebSocket as {"event": "trace_span", "span": {...}}
  - persisted to thinking_events with kind="span" by main.py's _ws_callback

Span types:
  "api_call"      — data API HTTP request (api_fetch.py)
  "llm_call"      — LLM invocation (tools/_llm.py)
  "param_resolve" — LLM-driven API parameter resolution (api_fetch.py)
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Awaitable


def make_span(
    span_type: str,
    task_id: str,
    *,
    status: str,
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a span dict. `status` is 'start' | 'ok' | 'error'."""
    span: dict[str, Any] = {
        "span_id": uuid.uuid4().hex[:8],
        "span_type": span_type,
        "task_id": task_id,
        "status": status,
        "ts_ms": int(time.monotonic() * 1000),
    }
    if input is not None:
        span["input"] = input
    if output is not None:
        span["output"] = output
    return span


def make_span_emit(
    task_id: str,
    ws_callback: Callable[[dict], Awaitable[None]] | None,
) -> Callable[[dict], Awaitable[None]]:
    """Return an async span_emit function bound to task_id and ws_callback.

    Calling span_emit(span) pushes {"event": "trace_span", "span": span}
    through ws_callback, which in main.py also persists to thinking_events.
    Errors are silently swallowed so a tracing failure never breaks execution.
    """
    async def _emit(span: dict) -> None:
        if ws_callback is None:
            return
        try:
            await ws_callback({"event": "trace_span", "span": span})
        except Exception:
            pass

    return _emit

"""Lightweight span instrumentation for API and LLM call tracing.

Spans are emitted via an async callable (span_emit) that is created per-task
in execution.py and per-phase in perception.py / planning.py, and threaded
through ToolInput (for the execution layer) or invoked directly. Each span:
  - is broadcast over WebSocket as {"event": "trace_span", "span": {...}}
  - is persisted to thinking_events with kind="span" by main.py's _ws_callback
    (which uses span.phase for the phase column, falling back to "execution")

Span types:
  "api_call"          — data API HTTP request (api_fetch.py)
  "llm_call"          — LLM invocation (tools/_llm.py)
  "param_resolve"     — LLM-driven API parameter resolution (api_fetch.py)
  "phase"             — outer span around a perception/planning node
  "planning_skeleton" — multi-round planning, round 1 (section outline)
  "planning_section"  — multi-round planning, round 2 (per-section fill)
  "planning_stitch"   — multi-round planning, round 3 (deterministic merge)
  "slot_fill"         — perception slot extraction LLM
  "clarify"           — perception clarification round LLM

Spans carry an optional ``task_name`` so the UI can render a human-readable
title (e.g. "T001 拉取吞吐量") instead of a bare task id, and an optional
``phase`` so the trace pane can group by phase (感知/规划/执行).
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Awaitable

logger = logging.getLogger("analytica.tracing")


def make_span(
    span_type: str,
    task_id: str,
    *,
    status: str,
    task_name: str | None = None,
    phase: str | None = None,
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a span dict. `status` is 'start' | 'ok' | 'error'.

    ``task_name`` and ``phase`` are optional; older callers that omit them
    keep producing the legacy shape. Frontend renders ``task_name || task_id``
    so absent task_name falls back gracefully.
    """
    span: dict[str, Any] = {
        "span_id": uuid.uuid4().hex[:8],
        "span_type": span_type,
        "task_id": task_id,
        "status": status,
        "ts_ms": int(time.monotonic() * 1000),
    }
    if task_name:
        span["task_name"] = task_name
    if phase:
        span["phase"] = phase
    if input is not None:
        span["input"] = input
    if output is not None:
        span["output"] = output
    return span


def make_span_emit(
    task_id: str,
    ws_callback: Callable[[dict], Awaitable[None]] | None,
    *,
    task_name: str | None = None,
    phase: str | None = None,
) -> Callable[[dict], Awaitable[None]]:
    """Return an async span_emit function bound to task_id and ws_callback.

    Calling span_emit(span) pushes {"event": "trace_span", "span": span}
    through ws_callback, which in main.py also persists to thinking_events.
    Errors are silently swallowed so a tracing failure never breaks execution.

    If ``task_name`` or ``phase`` are provided, the emitter back-fills them
    onto every emitted span when the caller didn't already set the field.
    Tools that call ``make_span(...)`` themselves can therefore stay
    unchanged: enrichment happens at emit time.
    """
    async def _emit(span: dict) -> None:
        if ws_callback is None:
            return
        if task_name and "task_name" not in span:
            span["task_name"] = task_name
        if phase and "phase" not in span:
            span["phase"] = phase
        try:
            await ws_callback({"event": "trace_span", "span": span})
        except Exception:
            pass

    return _emit


@asynccontextmanager
async def trace_span(
    span_type: str,
    task_id: str,
    *,
    task_name: str | None = None,
    phase: str | None = None,
    input: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Async context manager for emitting a paired start/ok|error span.

    The yielded dict is the span's ``output`` payload — callers fill in
    keys to surface in the trace pane (e.g. ``out["sections"] = 4``). On
    exception the wrapper auto-records ``error_type`` / ``error`` and
    re-raises; tracing failures are logged but never propagate.

    Pulls the current ws_callback from ``ws_ctx`` so callers don't need
    to thread it through. When no callback is active (tests, offline
    runs) emission becomes a no-op.

    Example:
        async with trace_span(
            "planning_skeleton", "planning.skeleton",
            task_name="规划-章节大纲", phase="planning",
            input={"complexity": "full_report"},
        ) as out:
            skel = await self._call_skeleton_llm(...)
            out["sections"] = len(skel.sections)
    """
    # Local import keeps the module import-cycle-free; ws_ctx imports nothing from here.
    from backend.agent import ws_ctx

    cb = ws_ctx.get_ws_callback()
    emit = make_span_emit(task_id, cb, task_name=task_name, phase=phase)

    output: dict[str, Any] = {}
    # Emit start (best-effort).
    try:
        await emit(make_span(span_type, task_id, status="start", input=input))
    except Exception:
        logger.debug("trace_span start emit failed", exc_info=True)

    error: BaseException | None = None
    try:
        yield output
    except BaseException as e:
        error = e
        raise
    finally:
        status = "error" if error is not None else "ok"
        if error is not None:
            output.setdefault("error_type", type(error).__name__)
            output.setdefault("error", str(error)[:200])
        try:
            await emit(make_span(
                span_type, task_id, status=status,
                output=output or None,
            ))
        except Exception:
            logger.debug("trace_span end emit failed", exc_info=True)

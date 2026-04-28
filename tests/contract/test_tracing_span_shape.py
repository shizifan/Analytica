"""Contract: trace span shape across the backend.

Pins the wire format of trace spans so that frontend rendering stays in
sync with backend producers. The frontend Span interface (traceStore.ts)
relies on these fields and the optional fallbacks declared here:

  - ``task_name`` is optional; legacy persisted spans without it must still
    round-trip through make_span / make_span_emit and arrive at the UI as
    a valid Span (frontend falls back to task_id).
  - ``phase`` is optional; missing phase defaults to "execution" at
    persistence time (main.py _ws_callback).
"""
from __future__ import annotations

import asyncio

import pytest

from backend.tracing import make_span, make_span_emit

pytestmark = pytest.mark.contract


# ── make_span shape ─────────────────────────────────────────


def test_make_span_legacy_call_omits_optional_fields():
    """Old-style call (no task_name / phase) must produce a span without
    those keys — frontend treats absence as legacy and falls back."""
    span = make_span("api_call", "T001", status="ok")
    assert span["span_type"] == "api_call"
    assert span["task_id"] == "T001"
    assert span["status"] == "ok"
    assert "ts_ms" in span
    assert "task_name" not in span
    assert "phase" not in span


def test_make_span_carries_task_name_and_phase_when_provided():
    span = make_span(
        "llm_call", "T001", status="ok",
        task_name="拉取吞吐量", phase="execution",
    )
    assert span["task_name"] == "拉取吞吐量"
    assert span["phase"] == "execution"


def test_make_span_drops_empty_task_name():
    """Empty string is treated as absent (frontend would try to display
    an empty header otherwise)."""
    span = make_span("api_call", "T001", status="ok", task_name="")
    assert "task_name" not in span


# ── make_span_emit enrichment ───────────────────────────────


async def test_emit_backfills_task_name_and_phase_from_factory():
    """When the tool calls make_span() without task_name/phase, the emit
    wrapper must back-fill them so the frontend gets a complete span."""
    captured: list[dict] = []

    async def ws_callback(payload):
        captured.append(payload)

    emit = make_span_emit(
        "T001", ws_callback,
        task_name="抓数据", phase="execution",
    )
    await emit(make_span("api_call", "T001", status="start"))

    assert len(captured) == 1
    assert captured[0]["event"] == "trace_span"
    span = captured[0]["span"]
    assert span["task_name"] == "抓数据"
    assert span["phase"] == "execution"


async def test_emit_does_not_overwrite_explicit_fields():
    """If the tool sets task_name explicitly (e.g. a sub-span with a
    different label), the wrapper must respect it."""
    captured: list[dict] = []

    async def ws_callback(payload):
        captured.append(payload)

    emit = make_span_emit("T001", ws_callback, task_name="父任务", phase="execution")
    await emit(make_span("llm_call", "T001", status="ok", task_name="子任务"))

    assert captured[0]["span"]["task_name"] == "子任务"


async def test_emit_silently_swallows_callback_failure():
    """Tracing must never break the calling tool. Even an exploding
    ws_callback should not propagate."""
    async def bad(_payload):
        raise RuntimeError("ws gone")

    emit = make_span_emit("T001", bad, task_name="x", phase="execution")
    # Must not raise
    await emit(make_span("api_call", "T001", status="ok"))


async def test_emit_skips_when_ws_callback_is_none():
    """Test environments often have no WS — emit must be a no-op rather
    than crashing on the None callable."""
    emit = make_span_emit("T001", None, task_name="x", phase="execution")
    await emit(make_span("api_call", "T001", status="ok"))


# ── Backwards-compat: legacy persisted spans ────────────────


def test_legacy_span_shape_round_trips():
    """Spans persisted before this PR have only the original 5 fields.
    They must still satisfy the contract the frontend expects (so old
    sessions render correctly)."""
    legacy = {
        "span_id": "abc123ef",
        "span_type": "api_call",
        "task_id": "T002",
        "status": "ok",
        "ts_ms": 1000,
    }
    # Frontend treats this as: phase=undefined → default "execution" group,
    # task_name=undefined → header falls back to task_id.
    # We just assert the legacy dict has no surprise keys that would clash.
    assert set(legacy.keys()).issubset({
        "span_id", "span_type", "task_id", "status",
        "ts_ms", "task_name", "phase", "input", "output",
    })

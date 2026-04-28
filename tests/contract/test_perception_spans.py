"""Contract: perception emits trace spans for slot extraction and clarification.

Pins the trace shape for the perception phase so the trace pane can
group slot_fill / clarify events under the 感知阶段 header. Uses a stub
LLM via SlotFillingEngine — no DB or graph node required.
"""
from __future__ import annotations

import json

import pytest

from backend.tools.loader import load_all_tools

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module", autouse=True)
def _ensure_tools_loaded():
    load_all_tools()


@pytest.fixture
def captured_spans(monkeypatch):
    """Capture every trace_span event flowing through ws_ctx."""
    from backend.agent import ws_ctx

    captured: list[dict] = []

    async def cb(payload):
        if payload.get("event") == "trace_span":
            captured.append(payload["span"])

    token = ws_ctx.set_ws_callback(cb)
    yield captured
    ws_ctx.reset_ws_callback(token)


def _make_engine(invoke):
    """Build a SlotFillingEngine with the given _invoke_llm coroutine."""
    from backend.agent.perception import SlotFillingEngine

    engine = SlotFillingEngine(
        llm=object(),
        memory_store=None,
        max_clarification_rounds=3,
        llm_timeout=10,
    )
    engine._invoke_llm = invoke
    return engine


async def test_extract_slots_emits_slot_fill_span(captured_spans):
    """extract_slots_from_text wraps its LLM call in a slot_fill span and
    records which slot names were extracted."""
    async def fake_invoke(prompt: str) -> str:
        return json.dumps({
            "extracted": {
                "analysis_subject": {"value": ["吞吐量"], "confidence": "explicit"},
                "time_range": {
                    "value": {
                        "start": "2026-04-01", "end": "2026-04-30",
                        "description": "2026年4月",
                    },
                    "confidence": "explicit",
                },
            },
        })

    engine = _make_engine(fake_invoke)
    await engine.extract_slots_from_text(
        text="出一份2026年4月吞吐量月报",
        current_slots={},
        conversation_history=[],
    )

    slot_spans = [s for s in captured_spans if s["span_type"] == "slot_fill"]
    assert any(s["status"] == "start" for s in slot_spans)
    end = next((s for s in slot_spans if s["status"] == "ok"), None)
    assert end is not None
    assert end["phase"] == "perception"
    assert end["task_name"] == "槽位填充"
    assert set(end["output"]["extracted_slots"]) == {"analysis_subject", "time_range"}


async def test_extract_slots_records_parse_error(captured_spans):
    """LLM returns garbage → slot_fill span ends ok but output.result
    flags the parse_error path so users can debug a flaky model."""
    async def fake_invoke(prompt: str) -> str:
        return "this is not json"

    engine = _make_engine(fake_invoke)
    await engine.extract_slots_from_text(
        text="x", current_slots={}, conversation_history=[],
    )
    end = next(
        (s for s in captured_spans
         if s["span_type"] == "slot_fill" and s["status"] == "ok"),
        None,
    )
    assert end is not None
    assert end["output"]["result"] == "parse_error"


async def test_clarify_single_slot_emits_clarify_span(captured_spans):
    async def fake_invoke(prompt: str) -> str:
        return "请问您需要分析哪个时间段？"

    engine = _make_engine(fake_invoke)
    await engine.generate_clarification_question(
        target_slot="time_range", slots={},
    )

    clar = [s for s in captured_spans if s["span_type"] == "clarify"]
    start = next((s for s in clar if s["status"] == "start"), None)
    end = next((s for s in clar if s["status"] == "ok"), None)
    assert start is not None and end is not None
    assert end["phase"] == "perception"
    assert end["output"]["question_chars"] > 0
    # input only ships on the start span — end carries output only
    assert start["input"]["target_slots"] == ["time_range"]


async def test_clarify_multi_slot_emits_clarify_span(captured_spans):
    async def fake_invoke(prompt: str) -> str:
        return "请问您需要分析的主题、时间段分别是什么？"

    engine = _make_engine(fake_invoke)
    await engine.generate_multi_slot_clarification(
        target_slots=["analysis_subject", "time_range"], slots={},
    )

    start = next(
        (s for s in captured_spans
         if s["span_type"] == "clarify" and s["status"] == "start"),
        None,
    )
    assert start is not None
    assert start["input"]["target_slots"] == ["analysis_subject", "time_range"]


async def test_clarify_falls_back_when_llm_returns_empty(captured_spans):
    """Empty LLM output triggers the deterministic fallback question;
    the span still completes ok with output.result tagged so users can
    see the model failed silently."""
    async def fake_invoke(prompt: str) -> str:
        return "   "  # whitespace-only → cleaned == ""

    engine = _make_engine(fake_invoke)
    out = await engine.generate_clarification_question(
        target_slot="time_range", slots={},
    )
    assert "请问您希望" in out  # used template fallback

    end = next(
        (s for s in captured_spans
         if s["span_type"] == "clarify" and s["status"] == "ok"),
        None,
    )
    assert end is not None
    assert end["output"]["result"] == "empty_output"

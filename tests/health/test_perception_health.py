"""Perception layer minimum sanity check.

Goal: with a deterministic mock LLM, perception produces a structured intent
with the right shape. NOT asserting specific slot values for specific
queries — that's a scenario test.
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.health


async def test_perception_runs_with_minimal_state(mock_llm, monkeypatch):
    """Perception node accepts a state with raw_query and returns a state
    with structured_intent populated."""
    # Patch the LLM builder so perception uses our mock.
    from backend.agent import graph as graph_mod
    monkeypatch.setattr(graph_mod, "build_llm", lambda *a, **kw: mock_llm)

    # Mock LLM responses for the two perception calls (slot extract + clarify).
    mock_llm.set_response("槽位提取专家", json.dumps({
        "extracted": {
            "analysis_subject": {"value": ["集装箱吞吐量"], "evidence": "x", "confidence": "explicit"},
            "time_range": {"value": {"start": "2026-01-01", "end": "2026-12-31", "description": "2026年"}, "evidence": "x", "confidence": "explicit"},
            "output_complexity": {"value": "simple_table", "evidence": "x", "confidence": "explicit"},
        },
    }))
    mock_llm.set_response("clarify", "请明确分析对象")

    from backend.agent.perception import run_perception

    state = {
        "messages": [{"role": "user", "content": "查 2026 年集装箱吞吐量"}],
        "raw_query": "查 2026 年集装箱吞吐量",
        "session_id": "smoke-perception",
    }
    out = await run_perception(state)
    intent = out.get("structured_intent")
    assert intent is not None, "perception did not produce structured_intent"
    assert "slots" in intent, "structured_intent missing slots field"


def test_slot_filling_engine_constructs():
    """SlotFillingEngine instantiates without error (catches import drift)."""
    from backend.agent.perception import SlotFillingEngine
    engine = SlotFillingEngine(llm=None)
    assert engine is not None

"""Integration tests for Memory Injection — Phase 4.

TC-INJ01 ~ TC-INJ06: Preference injection into perception layer,
correction rate downgrade, explicit input override, template injection.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.memory.store import MemoryStore
from backend.agent.perception import SlotFillingEngine
from backend.models.schemas import SlotValue


# ── Helper MockLLM ───────────────────────────────────────────

class _FakeAIMessage:
    def __init__(self, content: str):
        self.content = content


class InjectMockLLM:
    """Mock LLM for injection tests."""

    def __init__(self, default_response: str | None = None):
        self._default = default_response or '{"extracted": {}}'

    async def ainvoke(self, prompt: str) -> _FakeAIMessage:
        return _FakeAIMessage(self._default)


# ── TC-INJ01: Second analysis auto-fills output_format ───────

@pytest.mark.asyncio
async def test_second_analysis_auto_fills_output_format(test_db_session):
    """TC-INJ01: After saving pptx preference, next analysis auto-fills output_format from memory."""
    user_id = str(uuid4())
    store = MemoryStore(session=test_db_session)

    # First analysis saved preference
    await store.upsert_preference(user_id, "output_format", "pptx")

    # Second analysis: initialize perception with memory
    llm = InjectMockLLM()
    engine = SlotFillingEngine(llm=llm, memory_store=store)
    user_prefs = await store.get_all_preferences(user_id)
    slots = engine.initialize_slots(user_prefs)

    assert slots["output_format"].value == "pptx"
    assert slots["output_format"].source == "memory"
    assert slots["output_format"].confirmed is False


# ── TC-INJ02: High correction rate downgrades slot ───────────

@pytest.mark.asyncio
async def test_high_correction_rate_downgrades_in_second_analysis(test_db_session):
    """TC-INJ02: High correction rate (80%) downgrades slot to memory_low_confidence."""
    user_id = str(uuid4())
    store = MemoryStore(session=test_db_session)

    # Save preference
    await store.upsert_preference(user_id, "output_format", "pptx")

    # Simulate 5 sessions, 4 corrections (80% correction rate)
    for i in range(5):
        sid = str(uuid4())
        await test_db_session.execute(
            text(
                "INSERT INTO sessions (session_id, user_id, state_json, created_at, updated_at) "
                "VALUES (:sid, :uid, '{}', NOW(), NOW())"
            ),
            {"sid": sid, "uid": user_id},
        )
        await test_db_session.flush()
        await store.record_slot(sid, "output_format", "pptx", "memory", 1)
        if i < 4:
            await store.mark_corrected(sid, "output_format")

    # Second analysis initialization
    llm = InjectMockLLM()
    engine = SlotFillingEngine(llm=llm, memory_store=store)
    user_prefs = await store.get_all_preferences(user_id)
    slots = engine.initialize_slots(user_prefs)
    await engine.apply_correction_rate_check(slots, user_id)

    assert slots["output_format"].source == "memory_low_confidence"


# ── TC-INJ03: Explicit user input overrides memory ───────────

@pytest.mark.asyncio
async def test_explicit_input_overrides_memory_preference(test_db_session):
    """TC-INJ03: User's explicit 'DOCX' overrides memory-based 'pptx'."""
    user_id = str(uuid4())
    store = MemoryStore(session=test_db_session)
    await store.upsert_preference(user_id, "output_format", "pptx")

    # LLM that extracts explicit docx
    llm = InjectMockLLM(json.dumps({
        "extracted": {
            "output_format": {
                "value": "docx",
                "evidence": "DOCX格式",
                "confidence": "explicit",
            }
        }
    }))

    engine = SlotFillingEngine(llm=llm, memory_store=store)
    user_prefs = await store.get_all_preferences(user_id)
    slots = engine.initialize_slots(user_prefs)
    assert slots["output_format"].value == "pptx"

    # User says DOCX explicitly
    updated = await engine.extract_slots_from_text("我要 DOCX 格式", slots, [])
    assert updated["output_format"].value == "docx"
    assert updated["output_format"].source == "user_input"


# ── TC-INJ05: Preference saved, available next analysis ──────

@pytest.mark.asyncio
async def test_preference_saved_in_reflection_available_next_analysis(test_db_session):
    """TC-INJ05: Reflection saves preferences -> next analysis perception reads them."""
    user_id = str(uuid4())
    store = MemoryStore(session=test_db_session)

    # Simulate reflection saving preferences
    await store.upsert_preference(user_id, "output_format", "pptx")
    await store.upsert_preference(user_id, "time_granularity", "monthly")

    # Next analysis initialization
    llm = InjectMockLLM()
    engine = SlotFillingEngine(llm=llm, memory_store=store)
    user_prefs = await store.get_all_preferences(user_id)
    slots = engine.initialize_slots(user_prefs)

    assert slots["output_format"].value == "pptx"
    assert slots["time_granularity"].value == "monthly"
    assert slots["output_format"].source == "memory"
    assert slots["time_granularity"].source == "memory"


# ── TC-INJ06: Correction rate updates after mark_corrected ───

@pytest.mark.asyncio
async def test_slot_correction_rate_updates_after_mark(test_db_session):
    """TC-INJ06: Verify correction rate increases after mark_corrected call."""
    user_id = str(uuid4())
    store = MemoryStore(session=test_db_session)

    # 5 sessions with no corrections
    for i in range(5):
        sid = str(uuid4())
        await test_db_session.execute(
            text(
                "INSERT INTO sessions (session_id, user_id, state_json, created_at, updated_at) "
                "VALUES (:sid, :uid, '{}', NOW(), NOW())"
            ),
            {"sid": sid, "uid": user_id},
        )
        await test_db_session.flush()
        await store.record_slot(sid, "output_complexity", "simple_table", "inferred", 1)

    rate_before = await store.get_correction_rate(user_id, "output_complexity")
    assert rate_before == 0.0

    # New session with correction
    sid_new = str(uuid4())
    await test_db_session.execute(
        text(
            "INSERT INTO sessions (session_id, user_id, state_json, created_at, updated_at) "
            "VALUES (:sid, :uid, '{}', NOW(), NOW())"
        ),
        {"sid": sid_new, "uid": user_id},
    )
    await test_db_session.flush()
    await store.record_slot(sid_new, "output_complexity", "simple_table", "inferred", 1)
    await store.mark_corrected(sid_new, "output_complexity")

    rate_after = await store.get_correction_rate(user_id, "output_complexity")
    assert rate_after > 0.0

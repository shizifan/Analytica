"""Integration tests for Reflection API endpoint — Phase 4.

TC-RAPI01 ~ TC-RAPI02: POST /api/sessions/{id}/reflection/save.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.memory.store import MemoryStore
from backend.agent.reflection import save_reflection


# ── TC-RAPI01: Save preferences only ─────────────────────────

@pytest.mark.asyncio
async def test_save_preferences_only(test_db_session):
    """TC-RAPI01: save_preferences=True writes preferences; template not written."""
    user_id = str(uuid4())
    session_id = str(uuid4())
    store = MemoryStore(session=test_db_session)

    # Create session
    await store.create_session(session_id, user_id)

    reflection_summary = {
        "user_preferences": {
            "output_format": "pptx",
            "time_granularity": "monthly",
        },
        "analysis_template": {
            "template_name": "测试模板",
            "applicable_scenario": "测试场景",
            "plan_skeleton": {"tasks": []},
        },
        "skill_feedback": {},
        "slot_quality_review": {
            "slots_auto_filled_correctly": [],
            "slots_corrected": [],
            "slots_corrected_detail": {},
        },
    }

    saved = await save_reflection(
        session_id=session_id,
        reflection_summary=reflection_summary,
        save_preferences=True,
        save_template=False,
        save_skill_notes=False,
        user_id=user_id,
        db_session=test_db_session,
    )

    assert saved["preferences"] >= 1

    # Verify preferences written
    prefs = await store.get_all_preferences(user_id)
    assert prefs.get("output_format") == "pptx"

    # Verify templates NOT written
    templates = await store.find_templates(user_id, "general", "chart_text")
    assert len(templates) == 0


# ── TC-RAPI02: Ignore saves nothing ─────────────────────────

@pytest.mark.asyncio
async def test_ignore_saves_nothing(test_db_session):
    """TC-RAPI02: All save flags False -> no data written."""
    user_id = str(uuid4())
    session_id = str(uuid4())
    store = MemoryStore(session=test_db_session)

    await store.create_session(session_id, user_id)

    reflection_summary = {
        "user_preferences": {"output_format": "pptx"},
        "analysis_template": {
            "template_name": "模板",
            "applicable_scenario": "",
            "plan_skeleton": {},
        },
        "skill_feedback": {
            "well_performed": ["skill_api_fetch"],
            "issues_found": [],
            "suggestions": [],
        },
        "slot_quality_review": {
            "slots_auto_filled_correctly": [],
            "slots_corrected": [],
            "slots_corrected_detail": {},
        },
    }

    saved = await save_reflection(
        session_id=session_id,
        reflection_summary=reflection_summary,
        save_preferences=False,
        save_template=False,
        save_skill_notes=False,
        user_id=user_id,
        db_session=test_db_session,
    )

    assert saved["preferences"] == 0
    assert saved["template"] is False
    assert saved["skill_notes"] == 0

    # Verify nothing in DB
    count = await test_db_session.execute(
        text("SELECT COUNT(*) FROM user_preferences WHERE user_id = :uid"),
        {"uid": user_id},
    )
    assert count.scalar() == 0


# ── TC-RAPI03: Save all includes slot correction marks ───────

@pytest.mark.asyncio
async def test_save_all_marks_corrected_slots(test_db_session):
    """TC-RAPI03: Full save marks corrected slots in slot_history."""
    user_id = str(uuid4())
    session_id = str(uuid4())
    store = MemoryStore(session=test_db_session)

    await store.create_session(session_id, user_id)

    # Pre-record a slot
    await store.record_slot(session_id, "output_complexity", "simple_table", "inferred", 1)

    reflection_summary = {
        "user_preferences": {"output_format": "docx"},
        "analysis_template": None,
        "skill_feedback": {
            "well_performed": ["skill_api_fetch"],
            "issues_found": [],
            "suggestions": [],
        },
        "slot_quality_review": {
            "slots_auto_filled_correctly": [],
            "slots_corrected": ["output_complexity"],
            "slots_corrected_detail": {
                "output_complexity": {"from": "simple_table", "to": "chart_text"},
            },
        },
    }

    saved = await save_reflection(
        session_id=session_id,
        reflection_summary=reflection_summary,
        save_preferences=True,
        save_template=False,
        save_skill_notes=True,
        user_id=user_id,
        db_session=test_db_session,
    )

    assert saved["slots_corrected"] == 1
    assert saved["skill_notes"] >= 1

    # Verify slot was marked corrected
    result = await test_db_session.execute(
        text(
            "SELECT was_corrected FROM slot_history "
            "WHERE session_id = :sid AND slot_name = 'output_complexity'"
        ),
        {"sid": session_id},
    )
    assert result.scalar() == 1

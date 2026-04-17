"""Tests for MemoryStore — Phase 4 Sprint 11.

TC-MS01 ~ TC-MS14: Full CRUD for user_preferences, analysis_templates,
slot_history, and skill_notes.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.memory.store import MemoryStore


# ── TC-MS01: upsert_preference insert ────────────────────────

@pytest.mark.asyncio
async def test_upsert_preference_insert(test_db_session):
    """TC-MS01: Verify first-time preference insert succeeds."""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    await store.upsert_preference(user_id, "output_format", {"v": "pptx"})
    result = await store.get_preference(user_id, "output_format")
    assert result == {"v": "pptx"}


# ── TC-MS02: upsert_preference update ────────────────────────

@pytest.mark.asyncio
async def test_upsert_preference_update(test_db_session):
    """TC-MS02: Verify upsert updates existing preference without duplicating rows."""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    await store.upsert_preference(user_id, "output_format", {"v": "pptx"})
    await store.upsert_preference(user_id, "output_format", {"v": "docx"})
    result = await store.get_preference(user_id, "output_format")
    assert result == {"v": "docx"}
    # Verify only one row
    count = await test_db_session.execute(
        text(
            "SELECT COUNT(*) FROM user_preferences WHERE user_id = :uid AND `key` = 'output_format'"
        ),
        {"uid": user_id},
    )
    assert count.scalar() == 1


# ── TC-MS03: get_all_preferences merges ──────────────────────

@pytest.mark.asyncio
async def test_get_all_preferences_merges(test_db_session):
    """TC-MS03: Verify get_all_preferences merges multiple keys into one dict."""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    await store.upsert_preference(user_id, "output_format", "pptx")
    await store.upsert_preference(user_id, "time_granularity", "monthly")
    await store.upsert_preference(user_id, "domain_glossary", {"货量": "throughput_teu"})
    prefs = await store.get_all_preferences(user_id)
    assert prefs["output_format"] == "pptx"
    assert prefs["time_granularity"] == "monthly"
    assert prefs["domain_glossary"]["货量"] == "throughput_teu"


# ── TC-MS04: get_preference nonexistent returns None ─────────

@pytest.mark.asyncio
async def test_get_preference_nonexistent_returns_none(test_db_session):
    """TC-MS04: Verify get_preference returns None for unknown key."""
    store = MemoryStore(session=test_db_session)
    result = await store.get_preference(str(uuid4()), "nonexistent_key")
    assert result is None


# ── TC-MS05: save_template + find_templates ──────────────────

@pytest.mark.asyncio
async def test_save_and_find_template(test_db_session):
    """TC-MS05: Verify save_template + find_templates round-trip."""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    template_id = await store.save_template(
        user_id=user_id,
        name="月度吞吐量分析",
        domain="port_ops",
        output_complexity="simple_table",
        tags=["throughput", "monthly"],
        plan_skeleton={"tasks": [{"type": "data_fetch"}]},
    )
    templates = await store.find_templates(user_id, "port_ops", "simple_table")
    assert len(templates) >= 1
    assert templates[0]["name"] == "月度吞吐量分析"
    assert templates[0]["template_id"] == template_id


# ── TC-MS06: find_templates exact match first ────────────────

@pytest.mark.asyncio
async def test_find_templates_exact_match_first(test_db_session):
    """TC-MS06: Verify exact match (domain+complexity) template is returned first."""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    exact_id = await store.save_template(user_id, "精确匹配模板", "port_ops", "simple_table", [], {})
    _fuzzy_id = await store.save_template(user_id, "模糊匹配模板", "port_ops", "chart_text", [], {})
    templates = await store.find_templates(user_id, "port_ops", "simple_table")
    assert templates[0]["template_id"] == exact_id


# ── TC-MS07: find_templates fallback to domain ───────────────

@pytest.mark.asyncio
async def test_find_templates_fallback_to_domain(test_db_session):
    """TC-MS07: Verify fallback to domain-only match when no exact match."""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    domain_id = await store.save_template(user_id, "域级模板", "port_ops", "chart_text", [], {})
    templates = await store.find_templates(user_id, "port_ops", "simple_table")
    assert len(templates) >= 1
    assert templates[0]["template_id"] == domain_id


# ── TC-MS08: find_templates fallback to user level ───────────

@pytest.mark.asyncio
async def test_find_templates_fallback_to_user_level(test_db_session):
    """TC-MS08: Verify fallback to user-level (highest usage_count) when no domain match."""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    id_high = await store.save_template(user_id, "高使用量模板", "finance", "full_report", [], {})
    await test_db_session.execute(
        text("UPDATE analysis_templates SET usage_count = 10 WHERE template_id = :tid"),
        {"tid": id_high},
    )
    await test_db_session.flush()
    _id_low = await store.save_template(user_id, "低使用量模板", "hr", "simple_table", [], {})
    templates = await store.find_templates(user_id, "port_ops", "simple_table")
    assert templates[0]["template_id"] == id_high  # Highest usage_count


# ── TC-MS09: increment_usage ─────────────────────────────────

@pytest.mark.asyncio
async def test_increment_usage(test_db_session):
    """TC-MS09: Verify increment_usage increases usage_count by 1."""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    tid = await store.save_template(user_id, "测试模板", "port_ops", "simple_table", [], {})
    await store.increment_usage(tid)
    await store.increment_usage(tid)
    result = await test_db_session.execute(
        text("SELECT usage_count FROM analysis_templates WHERE template_id = :tid"),
        {"tid": tid},
    )
    assert result.scalar() == 2


# ── TC-MS10: record_slot writes history ──────────────────────

@pytest.mark.asyncio
async def test_record_slot_written(test_db_session):
    """TC-MS10: Verify record_slot writes to slot_history."""
    store = MemoryStore(session=test_db_session)
    session_id = str(uuid4())
    await store.record_slot(
        session_id, "time_range",
        {"start": "2026-01-01", "end": "2026-01-31"},
        "user_input", round_num=1,
    )
    result = await test_db_session.execute(
        text("SELECT slot_name, source, was_corrected FROM slot_history WHERE session_id = :sid"),
        {"sid": session_id},
    )
    row = result.fetchone()
    assert row[0] == "time_range"
    assert row[1] == "user_input"
    assert row[2] == 0  # Default: not corrected


# ── TC-MS11: mark_corrected ──────────────────────────────────

@pytest.mark.asyncio
async def test_mark_corrected(test_db_session):
    """TC-MS11: Verify mark_corrected sets was_corrected=1."""
    store = MemoryStore(session=test_db_session)
    session_id = str(uuid4())
    await store.record_slot(session_id, "output_complexity", "simple_table", "inferred", 1)
    await store.mark_corrected(session_id, "output_complexity")
    result = await test_db_session.execute(
        text(
            "SELECT was_corrected FROM slot_history "
            "WHERE session_id = :sid AND slot_name = 'output_complexity'"
        ),
        {"sid": session_id},
    )
    assert result.scalar() == 1


# ── TC-MS12: get_correction_rate accurate ────────────────────

@pytest.mark.asyncio
async def test_get_correction_rate_accurate(test_db_session):
    """TC-MS12: Verify correction rate: 5 sessions, 2 corrected = 40%."""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    for i in range(5):
        session_id = str(uuid4())
        await test_db_session.execute(
            text(
                "INSERT INTO sessions (session_id, user_id, state_json, created_at, updated_at) "
                "VALUES (:sid, :uid, '{}', NOW(), NOW())"
            ),
            {"sid": session_id, "uid": user_id},
        )
        await test_db_session.flush()
        await store.record_slot(session_id, "output_complexity", "inferred_val", "inferred", 1)
        if i < 2:  # First 2 corrected
            await store.mark_corrected(session_id, "output_complexity")
    rate = await store.get_correction_rate(user_id, "output_complexity", lookback_sessions=10)
    assert abs(rate - 0.4) < 0.05  # Allow small float tolerance


# ── TC-MS13: upsert_skill_note updates ───────────────────────

@pytest.mark.asyncio
async def test_upsert_skill_note_updates(test_db_session):
    """TC-MS13: Verify upsert_skill_note updates existing record (no duplicate)."""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    await store.upsert_skill_note(user_id, "skill_desc_analysis", "首次备注", 0.7)
    await store.upsert_skill_note(user_id, "skill_desc_analysis", "更新备注", 0.9)
    notes = await store.get_skill_notes(user_id)
    assert notes["skill_desc_analysis"]["notes"] == "更新备注"
    assert notes["skill_desc_analysis"]["performance_score"] == 0.9
    # Only one row
    count = await test_db_session.execute(
        text(
            "SELECT COUNT(*) FROM skill_notes "
            "WHERE user_id = :uid AND skill_id = 'skill_desc_analysis'"
        ),
        {"uid": user_id},
    )
    assert count.scalar() == 1


# ── TC-MS14: tags JSON_CONTAINS query ────────────────────────

@pytest.mark.asyncio
async def test_template_tags_json_contains_query(test_db_session):
    """TC-MS14: Verify MySQL JSON_CONTAINS correctly queries tags array."""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    await store.save_template(
        user_id, "含 throughput 标签", "port_ops", "simple_table",
        tags=["throughput", "monthly"], plan_skeleton={},
    )
    await store.save_template(
        user_id, "不含该标签", "port_ops", "simple_table",
        tags=["revenue", "quarterly"], plan_skeleton={},
    )
    result = await test_db_session.execute(
        text(
            "SELECT name FROM analysis_templates "
            "WHERE user_id = :uid AND JSON_CONTAINS(tags, JSON_QUOTE('throughput'))"
        ),
        {"uid": user_id},
    )
    names = [row[0] for row in result.fetchall()]
    assert "含 throughput 标签" in names
    assert "不含该标签" not in names

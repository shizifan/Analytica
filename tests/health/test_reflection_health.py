"""Reflection layer minimum sanity check.

Mock LLM gives a standard reflection JSON; we verify that the layer
parses it, exposes a ReflectionSummary-shaped dict, and the persist
helper writes to the right tables.
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.health


def test_reflection_parses_summary_dict():
    """`format_reflection_card` accepts a normal summary dict."""
    from backend.agent.reflection import format_reflection_card

    summary = {
        "user_preferences": {"prefer_table": True},
        "analysis_template": None,
        "tool_feedback": {"well_performed": ["tool_api_fetch"], "issues_found": []},
        "slot_quality_review": {
            "slots_auto_filled_correctly": ["domain"],
            "slots_corrected": [],
            "slots_corrected_detail": {},
        },
    }
    md = format_reflection_card(summary)
    assert isinstance(md, str)
    assert len(md) > 0


async def test_reflection_save_persists_to_tool_notes(test_db_session):
    """save_reflection writes tool_notes row (regression for skill_notes
    rename: catches any leftover INSERT INTO skill_notes)."""
    from backend.agent.reflection import save_reflection
    from sqlalchemy import text

    summary = {
        "user_preferences": {},
        "analysis_template": None,
        "tool_feedback": {"well_performed": ["tool_api_fetch"], "issues_found": []},
        "slot_quality_review": {
            "slots_auto_filled_correctly": [],
            "slots_corrected": [],
            "slots_corrected_detail": {},
        },
    }
    saved = await save_reflection(
        session_id="health-reflection-smoke",
        reflection_summary=summary,
        save_preferences=False,
        save_template=False,
        save_tool_notes=True,
        user_id="health_user",
        db_session=test_db_session,
    )
    assert "tool_notes" in saved, f"save_reflection returned {saved}"

    # Confirm a row was written to tool_notes (not skill_notes which no longer exists)
    rows = await test_db_session.execute(
        text("SELECT COUNT(*) FROM tool_notes WHERE user_id = :uid"),
        {"uid": "health_user"},
    )
    count = rows.scalar()
    assert count is not None and count >= 1, (
        "tool_notes row not written — reflection persistence broken"
    )

    # Cleanup
    await test_db_session.execute(
        text("DELETE FROM tool_notes WHERE user_id = :uid"),
        {"uid": "health_user"},
    )
    await test_db_session.commit()

"""Phase 2: DAL round-trip tests for chat_messages / thinking_events / sessions rail."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.memory import session_log
from backend.memory.store import MemoryStore


@pytest_asyncio.fixture(loop_scope="function")
async def fresh_session(test_db_session):
    """Create a session row + yield sid; clean rows on teardown."""
    sid = f"test-phase2-{uuid.uuid4().hex[:8]}"
    store = MemoryStore(test_db_session)
    await store.create_session(sid, "test-user", employee_id=None)
    yield sid
    for tbl in ("chat_messages", "thinking_events", "sessions"):
        await test_db_session.execute(
            text(f"DELETE FROM {tbl} WHERE session_id = :s"),
            {"s": sid},
        )
    await test_db_session.commit()


@pytest.mark.asyncio(loop_scope="function")
async def test_append_and_list_chat_messages(fresh_session, test_db_session):
    sid = fresh_session
    db = test_db_session

    user_id = await session_log.append_chat_message(
        db, sid, role="user", content="你好",
    )
    assistant_id = await session_log.append_chat_message(
        db, sid, role="assistant", content="收到", phase="perception",
    )
    assert assistant_id > user_id

    rows = await session_log.list_chat_messages(db, sid)
    assert len(rows) == 2
    assert rows[0]["role"] == "user"
    assert rows[1]["role"] == "assistant"
    assert rows[1]["phase"] == "perception"

    only_assistant = await session_log.list_chat_messages(db, sid, since_id=user_id)
    assert len(only_assistant) == 1
    assert only_assistant[0]["id"] == assistant_id


@pytest.mark.asyncio(loop_scope="function")
async def test_append_and_list_thinking_events(fresh_session, test_db_session):
    sid = fresh_session
    db = test_db_session

    t1 = await session_log.append_thinking_event(
        db, sid, kind="phase",
        payload={"event": "phase_enter", "node": "perception"},
        phase="perception",
    )
    t2 = await session_log.append_thinking_event(
        db, sid, kind="tool",
        payload={"event": "tool_call_start", "task_id": "T1"},
        phase="execution",
    )
    assert t2 > t1

    all_events = await session_log.list_thinking_events(db, sid)
    assert len(all_events) == 2
    assert {e["kind"] for e in all_events} == {"phase", "tool"}

    tools_only = await session_log.list_thinking_events(db, sid, kind="tool")
    assert len(tools_only) == 1
    assert tools_only[0]["payload"]["task_id"] == "T1"


@pytest.mark.asyncio(loop_scope="function")
async def test_list_sessions_rail(fresh_session, test_db_session):
    """Verify HistoryPane query returns the session with title."""
    sid = fresh_session
    db = test_db_session

    await session_log.update_session_title(db, sid, "港口 Q1 分析")
    items = await session_log.list_sessions(db, user_id="test-user")
    ours = [s for s in items if s["session_id"] == sid]
    assert len(ours) == 1
    assert ours[0]["title"] == "港口 Q1 分析"
    assert ours[0]["pinned"] is False


@pytest.mark.asyncio(loop_scope="function")
async def test_since_id_pagination(fresh_session, test_db_session):
    """Replay pagination: since_id should return strictly newer rows only."""
    sid = fresh_session
    db = test_db_session

    ids = [
        await session_log.append_chat_message(db, sid, role="user", content=f"m{i}")
        for i in range(5)
    ]
    # since_id = ids[1] → should return 3 rows (ids[2..4])
    rows = await session_log.list_chat_messages(db, sid, since_id=ids[1])
    assert [r["id"] for r in rows] == ids[2:]


@pytest.mark.asyncio(loop_scope="function")
async def test_list_sessions_filters_empty(fresh_session, test_db_session):
    """A freshly-created session without a title or messages must NOT
    surface in the default HistoryPane query (include_empty=False) but
    should appear when the flag is flipped on."""
    sid = fresh_session
    db = test_db_session

    default_visible = await session_log.list_sessions(db, user_id="test-user")
    assert all(s["session_id"] != sid for s in default_visible)

    all_visible = await session_log.list_sessions(
        db, user_id="test-user", include_empty=True,
    )
    assert any(s["session_id"] == sid for s in all_visible)

    # Giving it a title brings it back into the default view
    await session_log.update_session_title(db, sid, "hello")
    with_title = await session_log.list_sessions(db, user_id="test-user")
    assert any(s["session_id"] == sid for s in with_title)


@pytest.mark.asyncio(loop_scope="function")
async def test_title_only_set_once_and_skips_control_phrases(fresh_session, test_db_session):
    """Replays the WS title-seeding logic end to end:

    1. First real user message → sets title.
    2. Subsequent plan-confirmation phrases must NOT overwrite it.
    """
    sid = fresh_session
    db = test_db_session

    # Helper: replicate main.py's decision (DB-driven, not cached)
    control = {"确认执行", "修改方案", "重新规划"}

    async def seed_turn(msg: str) -> None:
        await session_log.append_chat_message(db, sid, role="user", content=msg)
        cur = (
            await db.execute(
                text("SELECT title FROM sessions WHERE session_id = :s"),
                {"s": sid},
            )
        ).scalar()
        if not cur and msg.strip() and msg.strip() not in control:
            await session_log.update_session_title(db, sid, msg.strip()[:80])

    await seed_turn("2026 年 Q1 吞吐量")
    await seed_turn("确认执行")
    await seed_turn("修改方案")

    title = (
        await db.execute(
            text("SELECT title FROM sessions WHERE session_id = :s"),
            {"s": sid},
        )
    ).scalar()
    assert title == "2026 年 Q1 吞吐量"


@pytest.mark.asyncio(loop_scope="function")
async def test_purge_empty_sessions(fresh_session, test_db_session):
    """purge_empty_sessions deletes title-less empty sessions (respecting age)."""
    sid = fresh_session
    db = test_db_session

    # Fresh session — too young to be purged (default cutoff 15 min)
    removed = await session_log.purge_empty_sessions(db)
    assert removed == 0
    still_there = (
        await db.execute(
            text("SELECT COUNT(*) FROM sessions WHERE session_id = :s"),
            {"s": sid},
        )
    ).scalar()
    assert still_there == 1

    # With cutoff=0 the row is eligible and should be removed
    removed = await session_log.purge_empty_sessions(db, older_than_minutes=0)
    assert removed >= 1
    gone = (
        await db.execute(
            text("SELECT COUNT(*) FROM sessions WHERE session_id = :s"),
            {"s": sid},
        )
    ).scalar()
    assert gone == 0

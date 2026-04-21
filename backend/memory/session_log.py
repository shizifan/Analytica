"""Data access layer for Phase 2 chat_messages and thinking_events tables.

Kept separate from `MemoryStore` so the graph pipeline's dependency on
preferences/templates/slot_history isn't entangled with the UI-facing
display projection tables. Functions accept an AsyncSession and commit
before returning — callers should use the same session factory as the
rest of the backend.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# Session start reference — used so ts_ms values on thinking_events stay
# compact and comparable within a single process run. For cross-process
# replay we compare `created_at` instead.
_PROCESS_START_MS = int(time.monotonic() * 1000)


def _now_ts_ms() -> int:
    return int(time.monotonic() * 1000) - _PROCESS_START_MS


async def append_chat_message(
    db: AsyncSession,
    session_id: str,
    role: str,
    content: str | None,
    *,
    type: str = "text",
    phase: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    """Insert a chat message and return its auto-generated id."""
    payload_json = json.dumps(payload, ensure_ascii=False, default=str) if payload else None
    result = await db.execute(
        text(
            """
            INSERT INTO chat_messages
                (session_id, role, type, phase, content, payload, created_at)
            VALUES
                (:sid, :role, :type, :phase, :content, :payload, NOW())
            """
        ),
        {
            "sid": session_id,
            "role": role,
            "type": type,
            "phase": phase,
            "content": content,
            "payload": payload_json,
        },
    )
    await db.commit()
    # MySQL driver returns last insert id via .lastrowid
    return int(result.lastrowid) if result.lastrowid else 0


async def append_thinking_event(
    db: AsyncSession,
    session_id: str,
    kind: str,
    payload: dict[str, Any] | None,
    *,
    phase: str | None = None,
    ts_ms: int | None = None,
) -> int:
    """Insert a thinking/tool/decision event and return its id."""
    payload_json = json.dumps(payload, ensure_ascii=False, default=str) if payload else None
    actual_ts = ts_ms if ts_ms is not None else _now_ts_ms()
    result = await db.execute(
        text(
            """
            INSERT INTO thinking_events
                (session_id, kind, phase, ts_ms, payload, created_at)
            VALUES
                (:sid, :kind, :phase, :ts, :payload, NOW())
            """
        ),
        {
            "sid": session_id,
            "kind": kind,
            "phase": phase,
            "ts": actual_ts,
            "payload": payload_json,
        },
    )
    await db.commit()
    return int(result.lastrowid) if result.lastrowid else 0


async def list_chat_messages(
    db: AsyncSession,
    session_id: str,
    *,
    since_id: int = 0,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return messages for a session ordered by id ascending."""
    rows = await db.execute(
        text(
            """
            SELECT id, session_id, role, type, phase, content, payload, created_at
            FROM chat_messages
            WHERE session_id = :sid AND id > :since
            ORDER BY id ASC
            LIMIT :lim
            """
        ),
        {"sid": session_id, "since": since_id, "lim": limit},
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        raw_payload = r[6]
        if isinstance(raw_payload, str):
            try:
                raw_payload = json.loads(raw_payload)
            except (json.JSONDecodeError, TypeError):
                pass
        out.append(
            {
                "id": int(r[0]),
                "session_id": r[1],
                "role": r[2],
                "type": r[3],
                "phase": r[4],
                "content": r[5],
                "payload": raw_payload,
                "created_at": r[7].isoformat() if r[7] else None,
            }
        )
    return out


async def list_thinking_events(
    db: AsyncSession,
    session_id: str,
    *,
    since_id: int = 0,
    kind: Optional[str] = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return thinking events for a session ordered by id ascending."""
    base_sql = (
        "SELECT id, session_id, kind, phase, ts_ms, payload, created_at "
        "FROM thinking_events WHERE session_id = :sid AND id > :since"
    )
    params: dict[str, Any] = {"sid": session_id, "since": since_id, "lim": limit}
    if kind:
        base_sql += " AND kind = :kind"
        params["kind"] = kind
    base_sql += " ORDER BY id ASC LIMIT :lim"

    rows = await db.execute(text(base_sql), params)
    out: list[dict[str, Any]] = []
    for r in rows:
        raw_payload = r[5]
        if isinstance(raw_payload, str):
            try:
                raw_payload = json.loads(raw_payload)
            except (json.JSONDecodeError, TypeError):
                pass
        out.append(
            {
                "id": int(r[0]),
                "session_id": r[1],
                "kind": r[2],
                "phase": r[3],
                "ts_ms": int(r[4]) if r[4] is not None else 0,
                "payload": raw_payload,
                "created_at": r[6].isoformat() if r[6] else None,
            }
        )
    return out


async def list_sessions(
    db: AsyncSession,
    *,
    user_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    include_deleted: bool = False,
    include_empty: bool = False,
) -> list[dict[str, Any]]:
    """Return sessions ordered by updated_at desc for the HistoryPane.

    By default filters out sessions that have neither a title nor any
    chat_messages rows — these are typically orphans created when the
    frontend mounted but the user never sent a message. Pass
    `include_empty=True` to see everything (admin / debugging).
    """
    where = ["1 = 1"]
    params: dict[str, Any] = {"lim": limit, "off": offset}
    if user_id is not None:
        where.append("s.user_id = :uid")
        params["uid"] = user_id
    if not include_deleted:
        where.append("s.deleted_at IS NULL")
    if not include_empty:
        where.append(
            "(s.title IS NOT NULL "
            "OR EXISTS (SELECT 1 FROM chat_messages m WHERE m.session_id = s.session_id))"
        )

    sql = (
        "SELECT s.session_id, s.user_id, s.employee_id, s.title, s.pinned, "
        "s.created_at, s.updated_at "
        "FROM sessions s WHERE " + " AND ".join(where) +
        " ORDER BY s.pinned DESC, s.updated_at DESC LIMIT :lim OFFSET :off"
    )
    rows = await db.execute(text(sql), params)
    return [
        {
            "session_id": r[0],
            "user_id": r[1],
            "employee_id": r[2],
            "title": r[3],
            "pinned": bool(r[4]),
            "created_at": r[5].isoformat() if r[5] else None,
            "updated_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]


async def purge_empty_sessions(
    db: AsyncSession,
    *,
    older_than_minutes: int = 15,
) -> int:
    """One-off / maintenance cleanup: delete sessions that were never used.

    "Never used" = no title AND no chat_messages rows. Only touches
    sessions older than `older_than_minutes` so freshly-created sessions
    waiting for a first message are preserved.
    """
    result = await db.execute(
        text(
            """
            DELETE FROM sessions
            WHERE title IS NULL
              AND TIMESTAMPDIFF(SECOND, created_at, NOW()) >= :secs
              AND NOT EXISTS (
                  SELECT 1 FROM chat_messages m WHERE m.session_id = sessions.session_id
              )
            """
        ),
        {"secs": older_than_minutes * 60},
    )
    await db.commit()
    return int(result.rowcount or 0)


async def update_session_title(
    db: AsyncSession, session_id: str, title: str,
) -> None:
    """Set / update a session's display title (first user message excerpt)."""
    await db.execute(
        text("UPDATE sessions SET title = :title WHERE session_id = :sid"),
        {"sid": session_id, "title": title[:255]},
    )
    await db.commit()

from __future__ import annotations
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class MemoryStore:
    """Handles MySQL operations for user preferences, slot history, etc."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_preferences(self, user_id: str) -> dict[str, Any]:
        """Load user preferences from MySQL."""
        result = await self.session.execute(
            text("SELECT `key`, value FROM user_preferences WHERE user_id = :uid"),
            {"uid": user_id},
        )
        prefs = {}
        for row in result:
            try:
                prefs[row[0]] = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (json.JSONDecodeError, TypeError):
                prefs[row[0]] = row[1]
        return prefs

    async def record_slot(
        self,
        session_id: str,
        slot_name: str,
        value: Any,
        source: str,
        round_num: int,
        was_corrected: bool = False,
    ) -> None:
        """Record a slot fill event in slot_history."""
        await self.session.execute(
            text("""
                INSERT INTO slot_history (id, session_id, slot_name, value, source, was_corrected, round_num)
                VALUES (:id, :sid, :name, :val, :src, :corrected, :round)
            """),
            {
                "id": str(uuid4()),
                "sid": session_id,
                "name": slot_name,
                "val": json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value,
                "src": source,
                "corrected": 1 if was_corrected else 0,
                "round": round_num,
            },
        )
        await self.session.commit()

    async def get_correction_rate(self, user_id: str, slot_name: str) -> float:
        """Get the correction rate for a specific slot based on history."""
        result = await self.session.execute(
            text("""
                SELECT
                    COUNT(*) as total,
                    SUM(was_corrected) as corrected
                FROM slot_history sh
                JOIN sessions s ON sh.session_id = s.session_id
                WHERE s.user_id = :uid AND sh.slot_name = :name
            """),
            {"uid": user_id, "name": slot_name},
        )
        row = result.first()
        if row is None or row[0] == 0:
            return 0.0
        return float(row[1] or 0) / float(row[0])

    async def save_session_state(self, session_id: str, state_json: dict) -> None:
        """Persist session state to MySQL."""
        await self.session.execute(
            text("""
                UPDATE sessions SET state_json = :state, updated_at = NOW()
                WHERE session_id = :sid
            """),
            {"sid": session_id, "state": json.dumps(state_json, ensure_ascii=False)},
        )
        await self.session.commit()

    async def create_session(self, session_id: str, user_id: str) -> None:
        """Create a new session record."""
        await self.session.execute(
            text("""
                INSERT INTO sessions (session_id, user_id, state_json)
                VALUES (:sid, :uid, :state)
            """),
            {"sid": session_id, "uid": user_id, "state": "{}"},
        )
        await self.session.commit()

    async def get_session(self, session_id: str) -> dict | None:
        """Get session record."""
        result = await self.session.execute(
            text("SELECT session_id, user_id, state_json, created_at FROM sessions WHERE session_id = :sid"),
            {"sid": session_id},
        )
        row = result.first()
        if row is None:
            return None
        state = row[2]
        if isinstance(state, str):
            try:
                state = json.loads(state)
            except json.JSONDecodeError:
                state = {}
        return {
            "session_id": row[0],
            "user_id": row[1],
            "state_json": state,
            "created_at": str(row[3]) if row[3] else None,
        }

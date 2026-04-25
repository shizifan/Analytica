from __future__ import annotations
import json
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class MemoryStore:
    """Handles MySQL operations for user preferences, slot history,
    analysis templates, and tool notes.

    Phase 4: Full CRUD with three-level fallback template query,
    correction rate with lookback, and upsert semantics.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── User Preferences ─────────────────────────────────────

    async def upsert_preference(self, user_id: str, key: str, value: Any) -> None:
        """Insert or update a user preference.

        Uses MySQL ON DUPLICATE KEY UPDATE (relies on UNIQUE(user_id, key)).
        """
        val_json = json.dumps(value, ensure_ascii=False, default=str)
        await self.session.execute(
            text("""
                INSERT INTO user_preferences (id, user_id, `key`, value, updated_at)
                VALUES (:id, :uid, :k, :val, NOW())
                ON DUPLICATE KEY UPDATE value = VALUES(value), updated_at = NOW()
            """),
            {"id": str(uuid4()), "uid": user_id, "k": key, "val": val_json},
        )
        await self.session.commit()

    async def get_all_preferences(self, user_id: str) -> dict[str, Any]:
        """Load all user preferences, merging into a single dict."""
        result = await self.session.execute(
            text("SELECT `key`, value FROM user_preferences WHERE user_id = :uid"),
            {"uid": user_id},
        )
        prefs: dict[str, Any] = {}
        for row in result:
            try:
                prefs[row[0]] = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            except (json.JSONDecodeError, TypeError):
                prefs[row[0]] = row[1]
        return prefs

    async def get_preference(self, user_id: str, key: str) -> Optional[Any]:
        """Get a single preference value, or None if not found."""
        result = await self.session.execute(
            text("SELECT value FROM user_preferences WHERE user_id = :uid AND `key` = :k"),
            {"uid": user_id, "k": key},
        )
        row = result.first()
        if row is None:
            return None
        try:
            return json.loads(row[0]) if isinstance(row[0], str) else row[0]
        except (json.JSONDecodeError, TypeError):
            return row[0]

    # Keep backward-compatible alias used by perception layer
    async def get_user_preferences(self, user_id: str) -> dict[str, Any]:
        """Alias for get_all_preferences (backward compatibility)."""
        return await self.get_all_preferences(user_id)

    # ── Analysis Templates ───────────────────────────────────

    async def save_template(
        self,
        user_id: str,
        name: str,
        domain: str,
        output_complexity: str,
        tags: list[str] | None = None,
        plan_skeleton: dict | None = None,
    ) -> str:
        """Save an analysis template. Returns the template_id."""
        template_id = str(uuid4())
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        skeleton_json = json.dumps(plan_skeleton or {}, ensure_ascii=False)
        await self.session.execute(
            text("""
                INSERT INTO analysis_templates
                    (template_id, user_id, name, domain, output_complexity, tags, plan_skeleton, usage_count, last_used)
                VALUES
                    (:tid, :uid, :name, :domain, :complexity, :tags, :skeleton, 0, NULL)
            """),
            {
                "tid": template_id,
                "uid": user_id,
                "name": name,
                "domain": domain,
                "complexity": output_complexity,
                "tags": tags_json,
                "skeleton": skeleton_json,
            },
        )
        await self.session.commit()
        return template_id

    async def find_templates(
        self,
        user_id: str,
        domain: str | None = None,
        output_complexity: str | None = None,
        limit: int = 3,
    ) -> list[dict]:
        """Find templates using three-level fallback query.

        Level 1: exact match (user_id + domain + output_complexity)
        Level 2: domain match (user_id + domain)
        Level 3: user-level (user_id only, highest usage_count)
        """
        # Level 1: exact match
        if domain and output_complexity:
            result = await self.session.execute(
                text("""
                    SELECT template_id, name, domain, output_complexity, tags,
                           plan_skeleton, usage_count, last_used
                    FROM analysis_templates
                    WHERE user_id = :uid AND domain = :domain AND output_complexity = :complexity
                    ORDER BY usage_count DESC
                    LIMIT :lim
                """),
                {"uid": user_id, "domain": domain, "complexity": output_complexity, "lim": limit},
            )
            templates = self._rows_to_template_dicts(result)
            if templates:
                return templates

        # Level 2: domain match
        if domain:
            result = await self.session.execute(
                text("""
                    SELECT template_id, name, domain, output_complexity, tags,
                           plan_skeleton, usage_count, last_used
                    FROM analysis_templates
                    WHERE user_id = :uid AND domain = :domain
                    ORDER BY usage_count DESC
                    LIMIT :lim
                """),
                {"uid": user_id, "domain": domain, "lim": limit},
            )
            templates = self._rows_to_template_dicts(result)
            if templates:
                return templates

        # Level 3: user-level fallback
        result = await self.session.execute(
            text("""
                SELECT template_id, name, domain, output_complexity, tags,
                       plan_skeleton, usage_count, last_used
                FROM analysis_templates
                WHERE user_id = :uid
                ORDER BY usage_count DESC
                LIMIT :lim
            """),
            {"uid": user_id, "lim": limit},
        )
        return self._rows_to_template_dicts(result)

    def _rows_to_template_dicts(self, result: Any) -> list[dict]:
        """Convert SQL result rows to template dicts."""
        templates = []
        for row in result:
            tags = row[4]
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except json.JSONDecodeError:
                    tags = []
            skeleton = row[5]
            if isinstance(skeleton, str):
                try:
                    skeleton = json.loads(skeleton)
                except json.JSONDecodeError:
                    skeleton = {}
            templates.append({
                "template_id": row[0],
                "name": row[1],
                "domain": row[2],
                "output_complexity": row[3],
                "tags": tags,
                "plan_skeleton": skeleton,
                "usage_count": row[6],
                "last_used": str(row[7]) if row[7] else None,
            })
        return templates

    async def increment_usage(self, template_id: str) -> None:
        """Increment usage_count and update last_used timestamp."""
        await self.session.execute(
            text("""
                UPDATE analysis_templates
                SET usage_count = usage_count + 1, last_used = NOW()
                WHERE template_id = :tid
            """),
            {"tid": template_id},
        )
        await self.session.commit()

    # ── Skill Notes ──────────────────────────────────────────

    async def upsert_tool_note(
        self,
        user_id: str,
        tool_id: str,
        notes: str,
        performance_score: float | None = None,
    ) -> None:
        """Insert or update a tool note (relies on UNIQUE(tool_id, user_id))."""
        await self.session.execute(
            text("""
                INSERT INTO tool_notes (id, tool_id, user_id, notes, performance_score, updated_at)
                VALUES (:id, :tool, :uid, :notes, :score, NOW())
                ON DUPLICATE KEY UPDATE
                    notes = VALUES(notes),
                    performance_score = VALUES(performance_score),
                    updated_at = NOW()
            """),
            {
                "id": str(uuid4()),
                "tool": tool_id,
                "uid": user_id,
                "notes": notes,
                "score": performance_score,
            },
        )
        await self.session.commit()

    async def get_tool_notes(self, user_id: str) -> dict[str, dict]:
        """Get all tool notes for a user, keyed by tool_id."""
        result = await self.session.execute(
            text("SELECT tool_id, notes, performance_score FROM tool_notes WHERE user_id = :uid"),
            {"uid": user_id},
        )
        notes: dict[str, dict] = {}
        for row in result:
            notes[row[0]] = {
                "notes": row[1],
                "performance_score": row[2],
            }
        return notes

    # ── Slot History ─────────────────────────────────────────

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
                "val": json.dumps(value, ensure_ascii=False, default=str),
                "src": source,
                "corrected": 1 if was_corrected else 0,
                "round": round_num,
            },
        )
        await self.session.commit()

    async def mark_corrected(self, session_id: str, slot_name: str) -> None:
        """Mark a slot as corrected in slot_history."""
        await self.session.execute(
            text("""
                UPDATE slot_history
                SET was_corrected = 1
                WHERE session_id = :sid AND slot_name = :name
            """),
            {"sid": session_id, "name": slot_name},
        )
        await self.session.commit()

    async def get_correction_rate(
        self, user_id: str, slot_name: str, lookback_sessions: int = 20
    ) -> float:
        """Get the correction rate for a slot based on recent history.

        Looks at the most recent `lookback_sessions` sessions for this user
        and calculates the fraction of times the slot was corrected.
        """
        result = await self.session.execute(
            text("""
                SELECT sh.was_corrected
                FROM slot_history sh
                JOIN sessions s ON sh.session_id = s.session_id
                WHERE s.user_id = :uid AND sh.slot_name = :name
                ORDER BY s.created_at DESC
                LIMIT :lookback
            """),
            {"uid": user_id, "name": slot_name, "lookback": lookback_sessions},
        )
        rows = result.fetchall()
        if not rows:
            return 0.0
        corrected = sum(1 for r in rows if r[0])
        return corrected / len(rows)

    # ── Session Management ───────────────────────────────────

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

    async def create_session(
        self, session_id: str, user_id: str, employee_id: str | None = None,
    ) -> None:
        """Create a new session record."""
        await self.session.execute(
            text("""
                INSERT INTO sessions (session_id, user_id, employee_id, state_json)
                VALUES (:sid, :uid, :eid, :state)
            """),
            {"sid": session_id, "uid": user_id, "eid": employee_id, "state": "{}"},
        )
        await self.session.commit()

    async def get_session(self, session_id: str) -> dict | None:
        """Get session record."""
        result = await self.session.execute(
            text("SELECT session_id, user_id, employee_id, state_json, created_at FROM sessions WHERE session_id = :sid"),
            {"sid": session_id},
        )
        row = result.first()
        if row is None:
            return None
        state = row[3]
        if isinstance(state, str):
            try:
                state = json.loads(state)
            except json.JSONDecodeError:
                state = {}
        return {
            "session_id": row[0],
            "user_id": row[1],
            "employee_id": row[2],
            "state_json": state,
            "created_at": str(row[4]) if row[4] else None,
        }

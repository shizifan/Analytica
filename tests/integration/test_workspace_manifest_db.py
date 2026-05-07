"""Integration tests for sessions.workspace_manifest_json column.

Covers V6 §5.2.6 — sessions created before V6 (NULL column) must
present as empty manifests when read through MemoryStore.get_session,
without any historical backfill happening at load time.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.memory.store import MemoryStore


pytestmark = pytest.mark.slow


class TestWorkspaceManifestColumn:

    async def test_new_session_has_empty_manifest(self, test_db_session):
        """A freshly-created session has DB column NULL → loader yields
        a canonical empty manifest dict, not None."""
        store = MemoryStore(test_db_session)
        sid = str(uuid4())
        await store.create_session(sid, "test_user_v6", employee_id=None)

        loaded = await store.get_session(sid)
        assert loaded is not None
        manifest = loaded["workspace_manifest_json"]
        assert isinstance(manifest, dict)
        assert manifest["session_id"] == sid
        assert manifest["items"] == {}

    async def test_explicit_manifest_roundtrips(self, test_db_session):
        """Writing a non-empty manifest via raw SQL → loader returns it
        verbatim with session_id / items keys preserved."""
        store = MemoryStore(test_db_session)
        sid = str(uuid4())
        await store.create_session(sid, "test_user_v6", employee_id=None)

        manifest_payload = {
            "session_id": sid,
            "items": {
                "T001": {
                    "task_id": "T001",
                    "turn_index": 0,
                    "type": "data_fetch",
                    "status": "done",
                    "turn_status": "finalized",
                    "user_confirmed": True,
                },
            },
        }
        await test_db_session.execute(
            text(
                "UPDATE sessions SET workspace_manifest_json = :m "
                "WHERE session_id = :sid"
            ),
            {"m": json.dumps(manifest_payload, ensure_ascii=False), "sid": sid},
        )
        await test_db_session.commit()

        loaded = await store.get_session(sid)
        assert loaded is not None
        manifest = loaded["workspace_manifest_json"]
        assert manifest["session_id"] == sid
        assert "T001" in manifest["items"]
        assert manifest["items"]["T001"]["status"] == "done"
        assert manifest["items"]["T001"]["user_confirmed"] is True

    async def test_null_manifest_does_not_backfill(self, test_db_session):
        """Reading a NULL manifest must not write anything back to DB —
        we want NULL to stay NULL until something genuinely lands in
        the workspace (no implicit empty-manifest persistence)."""
        store = MemoryStore(test_db_session)
        sid = str(uuid4())
        await store.create_session(sid, "test_user_v6", employee_id=None)

        # Read once via loader (empty manifest surfaced).
        await store.get_session(sid)

        # DB column is still NULL — loader did not write back.
        result = await test_db_session.execute(
            text(
                "SELECT workspace_manifest_json FROM sessions "
                "WHERE session_id = :sid"
            ),
            {"sid": sid},
        )
        row = result.first()
        assert row is not None
        assert row[0] is None

    async def test_corrupted_manifest_falls_back_to_empty(self, test_db_session):
        """If the JSON column happens to be malformed (e.g. legacy
        migration), loader yields the canonical empty manifest rather
        than crashing the request path."""
        store = MemoryStore(test_db_session)
        sid = str(uuid4())
        await store.create_session(sid, "test_user_v6", employee_id=None)
        # The MySQL JSON type rejects malformed JSON at the column level,
        # so we simulate the "string with non-dict shape" case (a list)
        # which is valid JSON but not a manifest.
        await test_db_session.execute(
            text(
                "UPDATE sessions SET workspace_manifest_json = :m "
                "WHERE session_id = :sid"
            ),
            {"m": json.dumps(["not", "a", "dict"]), "sid": sid},
        )
        await test_db_session.commit()

        loaded = await store.get_session(sid)
        assert loaded is not None
        manifest = loaded["workspace_manifest_json"]
        assert isinstance(manifest, dict)
        assert manifest["items"] == {}
        assert manifest["session_id"] == sid

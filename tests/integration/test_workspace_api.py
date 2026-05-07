"""V6 §10.2 / §5.3.3 — workspace REST + WebSocket integration tests.

Covers the three new endpoints introduced for S6:

  * GET    /api/sessions/{id}/workspace
  * POST   /api/sessions/{id}/workspace/{task_id}/confirm
  * POST   /api/sessions/{id}/workspace/{task_id}/unconfirm

…and the ``workspace_update`` event the confirm/unconfirm endpoints
broadcast to all WS subscribers of the session.

The tests drive the app via ``httpx.AsyncClient`` over an
``ASGITransport`` so all DB calls inside request handlers stay on the
same asyncio loop as the test coroutine — sync TestClient triggers a
"got Future attached to a different loop" mismatch with the cached
async SQLAlchemy engine. The DB row for the session is also written
through the async store to keep the loop boundary consistent.
"""
from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import httpx
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from backend.main import app
from backend.memory.session_workspace import SessionWorkspace
from backend.memory.store import MemoryStore
from backend.tools.base import ToolOutput
from tests.lib.multiturn_helpers import make_task

pytestmark = pytest.mark.slow


# ── fixtures ──────────────────────────────────────────────────

@pytest.fixture
def workspace_root(tmp_path, monkeypatch):
    """Point WORKSPACE_ROOT at a per-test tmp directory."""
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    yield tmp_path


@pytest.fixture
async def client():
    """Async client using FastAPI's ASGI transport — keeps the request
    handler on the same event loop as the test coroutine so the cached
    async DB engine doesn't see a loop mismatch."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver",
    ) as c:
        yield c


def _sync_delete_session(session_id: str) -> None:
    """Best-effort sync cleanup so a re-run doesn't accumulate rows."""
    db_url_sync = os.getenv(
        "DATABASE_URL_SYNC",
        "mysql+pymysql://root@localhost:3306/analytica",
    )
    eng = create_engine(db_url_sync)
    try:
        with eng.begin() as conn:
            conn.execute(
                text("DELETE FROM sessions WHERE session_id = :sid"),
                {"sid": session_id},
            )
    finally:
        eng.dispose()


@pytest.fixture
async def seeded_session(workspace_root, test_db_session):
    """Create a DB row + a workspace with two manifest items via the
    same async engine the request handler uses, so writes/reads share
    a connection pool.

    Returns ``session_id``. The workspace contains:
      * ``T001`` (data_fetch, 3-row dataframe, finalized)
      * ``T002`` (analysis, str, finalized)
    """
    session_id = str(uuid4())
    store = MemoryStore(test_db_session)
    await store.create_session(session_id, "user_v6", employee_id=None)

    ws = SessionWorkspace(session_id, workspace_root)
    ws.persist(
        make_task("T001"),
        ToolOutput(
            tool_id="t", status="success", output_type="dataframe",
            data=pd.DataFrame({"month": ["2026-01", "2026-02", "2026-03"],
                               "throughput": [100, 110, 105]}),
        ),
        turn_index=0,
    )
    ws.persist(
        make_task("T002", type="analysis", tool="tool_desc_analysis",
                  depends_on=["T001"], params={"data_ref": "T001"}),
        ToolOutput(
            tool_id="t", status="success", output_type="text",
            data="Q1 同比 +2.3%",
        ),
        turn_index=0,
    )
    ws.finalize_turn(0)
    yield session_id

    _sync_delete_session(session_id)


# ── GET manifest ──────────────────────────────────────────────

class TestGetWorkspaceManifest:

    async def test_returns_manifest_with_finalized_items(
        self, client, seeded_session,
    ):
        r = await client.get(f"/api/sessions/{seeded_session}/workspace")
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == seeded_session
        assert set(body["items"].keys()) == {"T001", "T002"}
        t001 = body["items"]["T001"]
        assert t001["status"] == "done"
        assert t001["turn_status"] == "finalized"
        assert t001["output_kind"] == "dataframe"
        # path is relative — never an absolute fs path
        assert t001["path"] == "T001.parquet"
        assert not os.path.isabs(t001["path"])

    async def test_returns_empty_manifest_for_session_without_workspace(
        self, client, workspace_root, test_db_session,
    ):
        """Session exists in DB but no workspace files → empty items."""
        sid = str(uuid4())
        store = MemoryStore(test_db_session)
        await store.create_session(sid, "u", employee_id=None)
        try:
            r = await client.get(f"/api/sessions/{sid}/workspace")
            assert r.status_code == 200
            body = r.json()
            assert body["session_id"] == sid
            assert body["items"] == {}
        finally:
            _sync_delete_session(sid)

    async def test_unknown_session_returns_404(
        self, client, workspace_root,
    ):
        r = await client.get("/api/sessions/does-not-exist/workspace")
        assert r.status_code == 404


# ── POST confirm / unconfirm ──────────────────────────────────

class TestConfirmUnconfirm:

    async def test_confirm_sets_user_confirmed_and_appends_history(
        self, client, seeded_session,
    ):
        r = await client.post(
            f"/api/sessions/{seeded_session}/workspace/T001/confirm",
            json={"actor": "alice"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["task_id"] == "T001"
        assert body["user_confirmed"] is True
        assert len(body["confirmed_history"]) == 1
        h = body["confirmed_history"][0]
        assert h["action"] == "confirm"
        assert h["actor"] == "alice"
        assert h["source"] == "user_marked"

        # Subsequent GET reflects the change
        r2 = await client.get(
            f"/api/sessions/{seeded_session}/workspace",
        )
        assert r2.json()["items"]["T001"]["user_confirmed"] is True

    async def test_unconfirm_appends_audit_entry(
        self, client, seeded_session,
    ):
        await client.post(
            f"/api/sessions/{seeded_session}/workspace/T001/confirm",
            json={"actor": "alice"},
        )
        r = await client.post(
            f"/api/sessions/{seeded_session}/workspace/T001/unconfirm",
            json={"actor": "alice"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["user_confirmed"] is False
        assert len(body["confirmed_history"]) == 2
        assert body["confirmed_history"][1]["action"] == "unconfirm"

    async def test_confirm_unknown_task_returns_404(
        self, client, seeded_session,
    ):
        r = await client.post(
            f"/api/sessions/{seeded_session}/workspace/GHOST/confirm",
            json={"actor": "alice"},
        )
        assert r.status_code == 404

    async def test_confirm_unknown_session_returns_404(
        self, client, workspace_root,
    ):
        r = await client.post(
            "/api/sessions/does-not-exist/workspace/T001/confirm",
            json={"actor": "alice"},
        )
        assert r.status_code == 404

    async def test_confirm_requires_actor(self, client, workspace_root):
        """``actor`` is mandatory so confirm-history always has
        attribution. Empty body → 422."""
        r = await client.post(
            "/api/sessions/anything/workspace/T001/confirm",
            json={},
        )
        assert r.status_code == 422

    async def test_double_confirm_is_idempotent_but_appends_history(
        self, client, seeded_session,
    ):
        await client.post(
            f"/api/sessions/{seeded_session}/workspace/T001/confirm",
            json={"actor": "alice"},
        )
        r = await client.post(
            f"/api/sessions/{seeded_session}/workspace/T001/confirm",
            json={"actor": "alice"},
        )
        assert r.status_code == 200
        # still confirmed; history grew
        body = r.json()
        assert body["user_confirmed"] is True
        assert len(body["confirmed_history"]) == 2


# ── WS broadcast ──────────────────────────────────────────────

class TestWorkspaceUpdateBroadcast:
    """Confirm endpoints publish ``workspace_update`` events to the
    SessionRegistry; subscribed queues see them right away."""

    async def test_confirm_broadcasts_workspace_update(
        self, client, seeded_session,
    ):
        from backend.agent.session_registry import get_registry
        registry = get_registry()
        q = registry.subscribe(seeded_session)

        try:
            r = await client.post(
                f"/api/sessions/{seeded_session}/workspace/T001/confirm",
                json={"actor": "alice"},
            )
            assert r.status_code == 200

            # broadcast is synchronous put_nowait — the queue should have
            # the payload by the time the HTTP response returns.
            assert not q.empty()
            ev = q.get_nowait()
            assert ev["event"] == "workspace_update"
            assert ev["session_id"] == seeded_session
            assert ev["task_id"] == "T001"
            assert ev["action"] == "confirm"
            assert ev["actor"] == "alice"
        finally:
            registry.unsubscribe(seeded_session, q)

    async def test_unconfirm_broadcasts_workspace_update(
        self, client, seeded_session,
    ):
        from backend.agent.session_registry import get_registry
        registry = get_registry()

        # confirm first (this also broadcasts) then drain.
        await client.post(
            f"/api/sessions/{seeded_session}/workspace/T001/confirm",
            json={"actor": "alice"},
        )
        q = registry.subscribe(seeded_session)
        try:
            r = await client.post(
                f"/api/sessions/{seeded_session}/workspace/T001/unconfirm",
                json={"actor": "alice"},
            )
            assert r.status_code == 200
            assert not q.empty()
            ev = q.get_nowait()
            assert ev["action"] == "unconfirm"
        finally:
            registry.unsubscribe(seeded_session, q)

    async def test_failed_confirm_does_not_broadcast(
        self, client, seeded_session,
    ):
        """If the underlying mark_confirmed raises (e.g. unknown
        task_id), no WS event should leak."""
        from backend.agent.session_registry import get_registry
        registry = get_registry()
        q = registry.subscribe(seeded_session)
        try:
            r = await client.post(
                f"/api/sessions/{seeded_session}/workspace/GHOST/confirm",
                json={"actor": "alice"},
            )
            assert r.status_code == 404
            assert q.empty(), "no WS event should fire on a 404"
        finally:
            registry.unsubscribe(seeded_session, q)

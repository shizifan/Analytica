"""Phase 5: artifact_store DAL + REST round trip."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backend.memory import artifact_store
from backend.memory.store import MemoryStore


@pytest_asyncio.fixture(loop_scope="function")
async def fresh_session_with_reports_dir(test_db_session, tmp_path, monkeypatch):
    """Isolate every test in its own REPORTS_DIR + session row."""
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    # Settings are cached via get_settings() — clear.
    from backend.config import get_settings
    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None

    sid = f"test-p5-{uuid.uuid4().hex[:8]}"
    store = MemoryStore(test_db_session)
    await store.create_session(sid, "test-user", employee_id=None)
    yield sid, tmp_path
    for tbl in ("report_artifacts", "chat_messages", "thinking_events", "sessions"):
        await test_db_session.execute(
            text(f"DELETE FROM {tbl} WHERE session_id = :s"), {"s": sid},
        )
    await test_db_session.commit()


@pytest.mark.asyncio(loop_scope="function")
async def test_persist_and_retrieve_html_artifact(
    fresh_session_with_reports_dir, test_db_session,
):
    sid, reports_dir = fresh_session_with_reports_dir
    db = test_db_session

    row = await artifact_store.persist_artifact(
        db,
        session_id=sid,
        task_id="T004",
        skill_id="skill_report_html",
        fmt="html",
        title="Q1 港口经营分析报告",
        content="<h1>Hello</h1>",
        meta={"chart_count": 2, "mode": "deterministic"},
    )
    assert row is not None
    assert row["format"] == "html"
    assert row["size_bytes"] > 0
    assert row["status"] == "ready"
    assert row["title"] == "Q1 港口经营分析报告"

    # File on disk
    fs_path = artifact_store.resolve_artifact_path(row)
    assert fs_path.exists()
    assert fs_path.read_text(encoding="utf-8") == "<h1>Hello</h1>"
    # Filename is prefixed with 8-char artifact id + sanitised title
    assert fs_path.name.endswith(".html")

    # DB round-trip
    fetched = await artifact_store.get_artifact(db, row["id"])
    assert fetched is not None
    assert fetched["id"] == row["id"]
    assert fetched["meta"]["chart_count"] == 2


@pytest.mark.asyncio(loop_scope="function")
async def test_binary_docx_bytes_preserved(
    fresh_session_with_reports_dir, test_db_session,
):
    """Raw bytes (DOCX/PPTX) must survive the round-trip byte-for-byte."""
    sid, _ = fresh_session_with_reports_dir
    db = test_db_session

    blob = os.urandom(512)
    row = await artifact_store.persist_artifact(
        db, session_id=sid, task_id="T005", skill_id="skill_report_docx",
        fmt="docx", title="T", content=blob, meta={"mode": "python_docx"},
    )
    assert row is not None
    fs_path = artifact_store.resolve_artifact_path(row)
    assert fs_path.read_bytes() == blob


@pytest.mark.asyncio(loop_scope="function")
async def test_list_artifacts_scoped_to_session(
    fresh_session_with_reports_dir, test_db_session,
):
    sid, _ = fresh_session_with_reports_dir
    db = test_db_session

    for i in range(3):
        await artifact_store.persist_artifact(
            db, session_id=sid, task_id=f"T00{i}",
            skill_id="skill_report_html", fmt="html",
            title=f"Report {i}", content=f"body {i}", meta={},
        )

    items = await artifact_store.list_artifacts(db, sid)
    assert len(items) == 3
    # Scoped to session (not leaking others)
    other = await artifact_store.list_artifacts(db, "no-such-session")
    assert other == []


@pytest.mark.asyncio(loop_scope="function")
async def test_download_endpoint_returns_file(
    fresh_session_with_reports_dir, test_db_session,
):
    from backend.main import app
    sid, _ = fresh_session_with_reports_dir
    db = test_db_session

    row = await artifact_store.persist_artifact(
        db, session_id=sid, task_id="T001",
        skill_id="skill_report_markdown", fmt="markdown",
        title="memo", content="# hello\n\n正文", meta={},
    )
    assert row is not None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # list endpoint
        list_resp = await client.get(f"/api/sessions/{sid}/reports")
        assert list_resp.status_code == 200
        assert list_resp.json()["count"] == 1

        # download
        dl = await client.get(f"/api/reports/{row['id']}/download")
        assert dl.status_code == 200
        assert b"hello" in dl.content
        cd = dl.headers.get("content-disposition", "")
        assert "attachment" in cd

        # preview for markdown returns inline file
        pv = await client.get(f"/api/reports/{row['id']}/preview")
        assert pv.status_code == 200
        assert "markdown" in pv.headers.get("content-type", "")


@pytest.mark.asyncio(loop_scope="function")
async def test_missing_artifact_returns_404(test_db_session):
    from backend.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/reports/{uuid.uuid4().hex}/download")
        assert resp.status_code == 404


@pytest.mark.asyncio(loop_scope="function")
async def test_missing_file_on_disk_returns_410(
    fresh_session_with_reports_dir, test_db_session,
):
    from backend.main import app
    sid, reports_dir = fresh_session_with_reports_dir
    db = test_db_session

    row = await artifact_store.persist_artifact(
        db, session_id=sid, task_id="T001", skill_id="skill_report_html",
        fmt="html", title="gone", content="x", meta={},
    )
    assert row is not None
    # Manually remove the file to simulate volume purge
    Path(artifact_store.resolve_artifact_path(row)).unlink()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/reports/{row['id']}/download")
        assert resp.status_code == 410

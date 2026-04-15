"""TC-API01~API05: 规划 API 端点测试。

使用 FastAPI TestClient + httpx AsyncClient 验证 GET/POST plan 端点。
"""
import json
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

import os
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from backend.main import app
from backend.database import get_session_factory


# ── Fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def create_session_with_plan(task_count: int = 3) -> str:
    """Create a test session with a pre-populated plan in state_json."""
    session_id = str(uuid4())
    user_id = "test_user"

    tasks = []
    for i in range(1, task_count + 1):
        tasks.append({
            "task_id": f"T{i:03d}",
            "type": "data_fetch" if i == 1 else "analysis",
            "name": f"任务{i}",
            "description": f"测试任务{i}",
            "depends_on": [f"T{i-1:03d}"] if i > 1 else [],
            "skill": "skill_api_fetch" if i == 1 else "skill_descriptive_analysis",
            "params": {"endpoint_id": "getThroughputSummary"} if i == 1 else {},
            "estimated_seconds": 10,
            "status": "pending",
            "output_ref": "",
        })

    state = {
        "structured_intent": {"analysis_goal": "测试"},
        "analysis_plan": {
            "plan_id": str(uuid4()),
            "version": 1,
            "title": "测试方案",
            "analysis_goal": "测试目标",
            "estimated_duration": task_count * 10,
            "tasks": tasks,
            "report_structure": None,
            "revision_log": [],
        },
        "plan_confirmed": False,
        "plan_version": 1,
    }

    from sqlalchemy import text as sa_text
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            sa_text("""
                INSERT INTO sessions (session_id, user_id, state_json)
                VALUES (:sid, :uid, :state)
            """),
            {"sid": session_id, "uid": user_id, "state": json.dumps(state, ensure_ascii=False)},
        )
        await session.commit()

    return session_id


async def cleanup_session(session_id: str) -> None:
    """Remove test session from DB."""
    from sqlalchemy import text as sa_text
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            sa_text("DELETE FROM sessions WHERE session_id = :sid"),
            {"sid": session_id},
        )
        await session.commit()


# ═══════════════════════════════════════════════════════════════
#  TC-API01: GET /api/sessions/{id}/plan 返回正确结构
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_plan_returns_correct_structure(client):
    sid = await create_session_with_plan(task_count=3)
    try:
        resp = await client.get(f"/api/sessions/{sid}/plan")
        assert resp.status_code == 200
        data = resp.json()
        assert "plan_id" in data
        assert "version" in data
        assert "tasks" in data
        assert "markdown_display" in data
        assert len(data["tasks"]) >= 2
    finally:
        await cleanup_session(sid)


# ═══════════════════════════════════════════════════════════════
#  TC-API02: GET plan 不存在的 session 返回 404
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_plan_nonexistent_session_returns_404(client):
    resp = await client.get("/api/sessions/nonexistent-id-12345/plan")
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
#  TC-API03: POST confirm 设置 plan_confirmed=True
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_confirm_plan_sets_confirmed(client):
    sid = await create_session_with_plan()
    try:
        resp = await client.post(
            f"/api/sessions/{sid}/plan/confirm",
            json={"confirmed": True, "modifications": []},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("plan_confirmed") is True
    finally:
        await cleanup_session(sid)


# ═══════════════════════════════════════════════════════════════
#  TC-API04: POST confirm 带删除任务修改
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_confirm_with_task_removal(client):
    sid = await create_session_with_plan(task_count=3)
    try:
        resp = await client.post(
            f"/api/sessions/{sid}/plan/confirm",
            json={
                "confirmed": True,
                "modifications": [{"type": "remove_task", "task_id": "T002"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        task_ids = [t["task_id"] for t in data["tasks"]]
        assert "T002" not in task_ids
        assert "T001" in task_ids
    finally:
        await cleanup_session(sid)


# ═══════════════════════════════════════════════════════════════
#  TC-API05: 幂等确认
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_confirm_plan_idempotent(client):
    sid = await create_session_with_plan()
    try:
        resp1 = await client.post(
            f"/api/sessions/{sid}/plan/confirm",
            json={"confirmed": True},
        )
        assert resp1.status_code == 200
        resp2 = await client.post(
            f"/api/sessions/{sid}/plan/confirm",
            json={"confirmed": True},
        )
        assert resp2.status_code == 200
    finally:
        await cleanup_session(sid)

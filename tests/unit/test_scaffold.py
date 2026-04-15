"""TC-S01 ~ TC-S08: 脚手架测试 — 数据库、API、配置验证。"""
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.database import Base

TEST_DATABASE_URL = "mysql+aiomysql://root@localhost:3306/analytica"

# Ensure config can load (will use real .env values from conftest)


@pytest_asyncio.fixture
async def test_db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


# ── TC-S01: 数据库表结构验证 ────────────────────────────────

@pytest.mark.asyncio
async def test_all_tables_created(test_db_engine):
    """验证 alembic upgrade head 创建了全部 5 张表"""
    async with test_db_engine.connect() as conn:
        result = await conn.execute(text("SHOW TABLES"))
        tables = {row[0] for row in result}
    expected = {"sessions", "user_preferences", "analysis_templates", "skill_notes", "slot_history"}
    assert expected.issubset(tables), f"缺少表: {expected - tables}"


# ── TC-S02: sessions 表字段类型验证 ─────────────────────────

@pytest.mark.asyncio
async def test_sessions_schema(test_db_engine):
    """验证 sessions 表 session_id 为 varchar(36)，无 uuid 类型"""
    async with test_db_engine.connect() as conn:
        result = await conn.execute(text("DESCRIBE sessions"))
        schema = {row[0]: row[1] for row in result}
    assert schema["session_id"].lower().startswith("varchar(36)"), f"session_id 类型应为 varchar(36), 实际: {schema['session_id']}"
    assert schema["state_json"].lower() in ("json", "longtext"), f"state_json 类型应为 json, 实际: {schema['state_json']}"
    assert "uuid" not in schema["session_id"].lower()


# ── TC-S03: 唯一约束验证 ───────────────────────────────────

@pytest.mark.asyncio
async def test_user_preferences_unique_constraint(test_db_session):
    """验证 user_preferences 表 UNIQUE(user_id, key) 约束有效"""
    user_id = str(uuid4())
    await test_db_session.execute(
        text("INSERT INTO user_preferences (id, user_id, `key`, value) VALUES (:id, :uid, :k, :v)"),
        {"id": str(uuid4()), "uid": user_id, "k": "output_format", "v": '"pptx"'},
    )
    await test_db_session.flush()
    with pytest.raises(Exception) as exc_info:
        await test_db_session.execute(
            text("INSERT INTO user_preferences (id, user_id, `key`, value) VALUES (:id, :uid, :k, :v)"),
            {"id": str(uuid4()), "uid": user_id, "k": "output_format", "v": '"docx"'},
        )
        await test_db_session.flush()
    assert "duplicate" in str(exc_info.value).lower() or "integrity" in str(exc_info.value).lower()


# ── TC-S04: upsert 语法验证 ────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_updates_existing(test_db_session):
    """验证 MySQL upsert 更新已有记录"""
    user_id = str(uuid4())
    row_id = str(uuid4())
    # Insert initial
    await test_db_session.execute(
        text("""
            INSERT INTO user_preferences (id, user_id, `key`, value, updated_at)
            VALUES (:id, :uid, :k, :v, NOW())
        """),
        {"id": row_id, "uid": user_id, "k": "output_format", "v": '"pptx"'},
    )
    await test_db_session.flush()
    # Upsert
    await test_db_session.execute(
        text("""
            INSERT INTO user_preferences (id, user_id, `key`, value, updated_at)
            VALUES (:id, :uid, :k, :v, NOW())
            ON DUPLICATE KEY UPDATE value=VALUES(value), updated_at=NOW()
        """),
        {"id": str(uuid4()), "uid": user_id, "k": "output_format", "v": '"docx"'},
    )
    await test_db_session.flush()
    result = await test_db_session.execute(
        text("SELECT value FROM user_preferences WHERE user_id=:uid AND `key`='output_format'"),
        {"uid": user_id},
    )
    rows = result.fetchall()
    # Due to unique constraint, the upsert should have updated the existing row
    assert len(rows) >= 1
    # The last value should be docx (since ON DUPLICATE KEY UPDATE updates the duplicate)
    values = [r[0] for r in rows]
    assert '"docx"' in values or any("docx" in str(v) for v in values)


# ── TC-S05: FastAPI 应用启动测试 ───────────────────────────

def test_app_starts():
    """验证 FastAPI 应用可正常启动，健康检查端点返回 200"""
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


# ── TC-S06: 会话创建 API ──────────────────────────────────

@pytest.mark.asyncio
async def test_create_session():
    """验证 POST /api/sessions 返回有效 session_id"""
    import httpx
    from backend.main import app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/sessions", json={"user_id": "test-user-001"})
    assert response.status_code == 201
    data = response.json()
    assert "session_id" in data
    assert len(data["session_id"]) == 36
    assert "-" in data["session_id"]


# ── TC-S07: WebSocket 连接测试 ─────────────────────────────

def test_websocket_connection():
    """验证 WebSocket 端点可建立连接"""
    from fastapi.testclient import TestClient
    from backend.main import app
    client = TestClient(app)
    session_id = "test-session-ws-001"
    with client.websocket_connect(f"/ws/chat/{session_id}") as ws:
        data = ws.receive_json()
        assert data.get("type") == "connected"
        assert data.get("session_id") == session_id
        ws.send_json({"type": "ping"})
        pong = ws.receive_json()
        assert pong.get("type") == "pong"


# ── TC-S08: 配置缺失时的错误处理 ──────────────────────────

def test_missing_env_raises_clear_error(monkeypatch):
    """验证 QWEN_API_BASE 缺失时给出清晰错误"""
    monkeypatch.delenv("QWEN_API_BASE", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        from backend.config import Settings
        Settings(_env_file=None)

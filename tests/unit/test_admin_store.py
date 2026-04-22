"""Phase 6 — admin_store DAL + REST smoke."""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backend.memory import admin_store


@pytest_asyncio.fixture(loop_scope="function")
async def clean_api(test_db_session):
    """Insert + clean one api_endpoints row."""
    name = f"test_api_{uuid.uuid4().hex[:8]}"
    yield name
    await test_db_session.execute(
        text("DELETE FROM api_endpoints WHERE name = :n"), {"n": name},
    )
    await test_db_session.commit()


@pytest.mark.asyncio(loop_scope="function")
async def test_upsert_and_list_api(clean_api, test_db_session):
    name = clean_api
    db = test_db_session
    await admin_store.upsert_api_endpoint(
        db,
        name=name,
        method="GET",
        path=f"/api/gateway/{name}",
        domain="D1",
        intent="test endpoint",
        tags=["test"],
        required_params=[],
        optional_params=["date"],
        source="mock",
        enabled=True,
    )
    items = await admin_store.list_api_endpoints(db, domain="D1")
    assert any(i["name"] == name for i in items)

    fetched = await admin_store.get_api_endpoint(db, name)
    assert fetched is not None
    assert fetched["tags"] == ["test"]
    assert fetched["enabled"] is True

    ok = await admin_store.delete_api_endpoint(db, name)
    assert ok is True
    again = await admin_store.delete_api_endpoint(db, name)
    assert again is False


@pytest.mark.asyncio(loop_scope="function")
async def test_api_stats_upsert_and_query(clean_api, test_db_session):
    name = clean_api
    db = test_db_session
    await admin_store.upsert_api_endpoint(
        db, name=name, method="GET", path="/x", domain="D1",
    )
    await admin_store.record_api_call(db, api_name=name, duration_ms=42, success=True)
    await admin_store.record_api_call(db, api_name=name, duration_ms=120, success=False)
    stats = await admin_store.get_api_stats(db, name, days=1)
    assert stats["total_calls"] == 2
    assert stats["total_errors"] == 1
    assert stats["error_rate"] == 0.5


@pytest.mark.asyncio(loop_scope="function")
async def test_audit_log_round_trip(test_db_session):
    db = test_db_session
    res_id = f"audit-{uuid.uuid4().hex[:6]}"
    await admin_store.append_audit(
        db,
        action="update",
        resource_type="api_endpoint",
        resource_id=res_id,
        actor_id="admin@local",
        actor_type="user",
        diff={"before": {"enabled": False}, "after": {"enabled": True}},
    )
    rows = await admin_store.list_audit(db, resource_type="api_endpoint", limit=10)
    assert any(r["resource_id"] == res_id for r in rows)

    await db.execute(
        text("DELETE FROM audit_logs WHERE resource_id = :r"),
        {"r": res_id},
    )
    await db.commit()


@pytest.mark.asyncio(loop_scope="function")
async def test_admin_list_endpoints_via_rest():
    from backend.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/admin/apis?limit=5")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and "count" in body

        r = await client.get("/api/admin/skills")
        assert r.status_code == 200
        assert r.json()["count"] >= 1

        r = await client.get("/api/admin/domains")
        assert r.status_code == 200
        domains = r.json()["items"]
        assert len(domains) == 7
        codes = {d["code"] for d in domains}
        assert codes == {"D1", "D2", "D3", "D4", "D5", "D6", "D7"}

        r = await client.get("/api/admin/audit?limit=5")
        assert r.status_code == 200

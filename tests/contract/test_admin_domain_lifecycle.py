"""Admin domain CRUD + reload-after-write contract.

Pins behaviour we rely on for the admin console (Phase 4):

  1. ``delete_domain`` refuses to remove a domain that still owns
     endpoints — the planning prompt would crash on a dangling
     ``ep.domain`` reference otherwise.
  2. ``delete_domain`` removes an empty domain successfully and
     reports True.
  3. After ``upsert_api_endpoint`` + ``reload_from_db``, the new
     endpoint is visible in ``BY_NAME`` (not stuck on stale data).
  4. After ``upsert_domain`` + ``reload_from_db``, the new domain
     is visible in ``DOMAIN_INDEX``.
  5. After ``delete_api_endpoint`` + ``reload_from_db``, the deleted
     name disappears from ``BY_NAME`` and ``VALID_ENDPOINT_IDS``.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import text

from backend.agent import api_registry
from backend.memory import admin_store

pytestmark = pytest.mark.contract


@contextmanager
def _save_and_restore_registry():
    """Snapshot module globals so reload_from_db calls can be reverted."""
    snap_endpoints = api_registry.ALL_ENDPOINTS
    snap_domain_index = dict(api_registry.DOMAIN_INDEX)
    snap_by_name = dict(api_registry.BY_NAME)
    snap_by_path = dict(api_registry.BY_PATH)
    snap_by_domain = {k: list(v) for k, v in api_registry.BY_DOMAIN.items()}
    snap_by_time = {k: list(v) for k, v in api_registry.BY_TIME.items()}
    snap_valid = set(api_registry.VALID_ENDPOINT_IDS)
    try:
        yield
    finally:
        api_registry.ALL_ENDPOINTS = snap_endpoints
        api_registry.DOMAIN_INDEX = snap_domain_index
        api_registry.BY_NAME.clear()
        api_registry.BY_NAME.update(snap_by_name)
        api_registry.BY_PATH.clear()
        api_registry.BY_PATH.update(snap_by_path)
        api_registry.BY_DOMAIN.clear()
        api_registry.BY_DOMAIN.update(snap_by_domain)
        api_registry.BY_TIME.clear()
        api_registry.BY_TIME.update(snap_by_time)
        api_registry.VALID_ENDPOINT_IDS.clear()
        api_registry.VALID_ENDPOINT_IDS.update(snap_valid)


async def _cleanup_endpoint(db, name: str) -> None:
    await db.execute(text("DELETE FROM api_endpoints WHERE name = :n"), {"n": name})
    await db.commit()


async def _cleanup_domain(db, code: str) -> None:
    await db.execute(text("DELETE FROM domains WHERE code = :c"), {"c": code})
    await db.commit()


# ── Domain delete safety ───────────────────────────────────────────


async def test_delete_domain_refuses_when_endpoints_still_reference_it(test_db_session):
    """D1 is seeded with dozens of endpoints — deleting it must raise
    so the operator notices before orphaning the endpoints."""
    with pytest.raises(ValueError, match="still owns"):
        await admin_store.delete_domain(test_db_session, "D1")


async def test_delete_domain_removes_empty_domain(test_db_session):
    """Create a fresh domain with no endpoints, then delete it cleanly."""
    code = "TST_EMP"  # VARCHAR(8) limit
    try:
        await admin_store.upsert_domain(
            test_db_session, code=code, name="empty test domain",
            description="t", color=None, top_tags=[],
        )
        ok = await admin_store.delete_domain(test_db_session, code)
        assert ok is True
    finally:
        await _cleanup_domain(test_db_session, code)


async def test_delete_domain_returns_false_when_missing(test_db_session):
    ok = await admin_store.delete_domain(test_db_session, "NXT")
    assert ok is False


async def test_count_endpoints_in_domain(test_db_session):
    """Sanity-check the helper: D1 has many endpoints, an unknown
    domain code returns 0."""
    n = await admin_store.count_endpoints_in_domain(test_db_session, "D1")
    assert n > 0
    n0 = await admin_store.count_endpoints_in_domain(test_db_session, "ZZZ")
    assert n0 == 0


# ── Reload-after-write contract ────────────────────────────────────


async def test_reload_after_endpoint_upsert_makes_it_visible(test_db_session):
    """The admin route's reload step must propagate new rows into the
    in-memory registry — otherwise admin saves wouldn't take effect
    until a restart."""
    name = "testReloadEndpoint"
    with _save_and_restore_registry():
        try:
            await admin_store.upsert_api_endpoint(
                test_db_session,
                name=name,
                method="GET",
                path=f"/api/test/{name}",
                domain="D1",  # piggy-back on a seeded domain
                intent="reload-after-write fixture",
            )
            assert name not in api_registry.BY_NAME  # not yet visible
            await api_registry.reload_from_db(test_db_session)
            assert name in api_registry.BY_NAME  # now visible
            assert name in api_registry.VALID_ENDPOINT_IDS
            ep = api_registry.BY_NAME[name]
            assert ep.path == f"/api/test/{name}"
            assert ep.intent == "reload-after-write fixture"
        finally:
            await _cleanup_endpoint(test_db_session, name)


async def test_reload_after_endpoint_delete_drops_it(test_db_session):
    """Deleted endpoints must disappear from ``BY_NAME`` after reload."""
    name = "testReloadDeleteEndpoint"
    with _save_and_restore_registry():
        await admin_store.upsert_api_endpoint(
            test_db_session, name=name, method="GET",
            path=f"/api/test/{name}", domain="D1", intent="will be deleted",
        )
        await api_registry.reload_from_db(test_db_session)
        assert name in api_registry.BY_NAME

        await admin_store.delete_api_endpoint(test_db_session, name)
        await api_registry.reload_from_db(test_db_session)
        assert name not in api_registry.BY_NAME
        assert name not in api_registry.VALID_ENDPOINT_IDS


async def test_reload_after_domain_upsert_makes_it_visible(test_db_session):
    """A new domain must appear in ``DOMAIN_INDEX`` after reload."""
    code = "TST_RLD"  # VARCHAR(8) limit
    with _save_and_restore_registry():
        try:
            await admin_store.upsert_domain(
                test_db_session, code=code, name="reload test domain",
                description="for the reload-after-write contract test",
                color=None, top_tags=["test"],
            )
            assert code not in api_registry.DOMAIN_INDEX  # not yet visible
            await api_registry.reload_from_db(test_db_session)
            assert code in api_registry.DOMAIN_INDEX
            d = api_registry.DOMAIN_INDEX[code]
            assert d.name == "reload test domain"
            assert "test" in d.top_tags
        finally:
            await _cleanup_domain(test_db_session, code)

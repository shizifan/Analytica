"""Lifespan hook contract — ``api_registry.lifespan_apply_source`` is the
sole entry point for populating the in-memory registry from the DB.

Three guarantees pinned here:

  1. **Happy path** — when the DB has rows, lifespan loads them and
     populates ``ALL_ENDPOINTS`` + ``DOMAIN_INDEX``.
  2. **Empty endpoints** — refuses to start with a clear error message
     pointing at ``tools.seed_api_endpoints``.
  3. **Empty domains** — same fail-fast behaviour.

The previous source-mode dispatcher (code/file/dual/dual_db) was removed
along with its tests; the registry now has a single source of truth (DB).
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest

from backend.agent import api_registry
from backend.agent.api_registry import lifespan_apply_source

pytestmark = pytest.mark.contract


@contextmanager
def _save_and_restore_registry():
    """Snapshot module globals so lifespan calls can be reverted between
    tests (the session-scope conftest fixture seeds the canonical state
    once; tests that mutate it must restore)."""
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


# ── Happy path ─────────────────────────────────────────────────


async def test_lifespan_populates_in_memory_registry(monkeypatch):
    """Lifespan must call reload_from_db and produce non-empty globals."""
    fake_reload = AsyncMock(return_value=(42, 5))
    monkeypatch.setattr(api_registry, "reload_from_db", fake_reload)

    await lifespan_apply_source()

    assert fake_reload.await_count == 1


# ── Fail-fast on empty data ────────────────────────────────────


async def test_lifespan_raises_when_endpoints_empty(monkeypatch):
    """An empty endpoints table must surface as a startup error pointing
    at the seed script — silent serving with no APIs would break LLM
    planning in confusing ways."""
    fake_reload = AsyncMock(return_value=(0, 5))
    monkeypatch.setattr(api_registry, "reload_from_db", fake_reload)

    with pytest.raises(RuntimeError, match="api_endpoints table is empty"):
        await lifespan_apply_source()


async def test_lifespan_raises_when_domains_empty(monkeypatch):
    """Same fail-fast rule for domains — endpoints reference domain codes
    so a missing domain table breaks the prompt formatter."""
    fake_reload = AsyncMock(return_value=(42, 0))
    monkeypatch.setattr(api_registry, "reload_from_db", fake_reload)

    with pytest.raises(RuntimeError, match="domains table is empty"):
        await lifespan_apply_source()


async def test_lifespan_propagates_db_errors(monkeypatch):
    """A DB read failure during reload must propagate (not be swallowed)
    so the operator sees the actual cause rather than a downstream
    KeyError when planning runs against an empty registry."""
    async def _boom(*a, **kw):
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(api_registry, "reload_from_db", _boom)

    with pytest.raises(RuntimeError, match="simulated DB outage"):
        await lifespan_apply_source()

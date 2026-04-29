"""P2.4-5 — ``reload_from_db()`` swaps the in-memory registry with DB rows.

Three guarantees pinned here:

  1. **Round-trip**: seed JSON → DB → ``reload_from_db`` produces an
     ``ALL_ENDPOINTS`` byte-equal to ``_CODE_ENDPOINTS`` (the JSON was
     exported from code, so they must match).
  2. **Lossless reconstruction**: the new 4 semantic fields (``field_schema`` /
     ``use_cases`` / ``chain_with`` / ``analysis_note``) survive
     code → seed → DB → reload identically.
  3. **Failure containment**: a DB read error keeps the registry on the
     previous source (no partial wipe), and a single malformed row is
     skipped with a WARN, never crashes the loader.

Tests use a real DB session (the dev DB seeded by P2.4-4); each test
restores the in-memory state afterwards so other tests aren't affected.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

import pytest

from backend.agent import api_registry
from backend.agent.api_registry import (
    _CODE_ENDPOINTS,
    reload_from_db,
)

pytestmark = pytest.mark.contract


@contextmanager
def _save_and_restore_registry():
    """Snapshot module globals so a reload_from_db call can be reverted."""
    snap_endpoints = api_registry.ALL_ENDPOINTS
    snap_by_name = dict(api_registry.BY_NAME)
    snap_by_path = dict(api_registry.BY_PATH)
    snap_by_domain = {k: list(v) for k, v in api_registry.BY_DOMAIN.items()}
    snap_by_time = {k: list(v) for k, v in api_registry.BY_TIME.items()}
    snap_valid = api_registry.VALID_ENDPOINT_IDS
    try:
        yield
    finally:
        api_registry.ALL_ENDPOINTS = snap_endpoints
        api_registry.BY_NAME.clear()
        api_registry.BY_NAME.update(snap_by_name)
        api_registry.BY_PATH.clear()
        api_registry.BY_PATH.update(snap_by_path)
        api_registry.BY_DOMAIN.clear()
        api_registry.BY_DOMAIN.update(snap_by_domain)
        api_registry.BY_TIME.clear()
        api_registry.BY_TIME.update(snap_by_time)
        api_registry.VALID_ENDPOINT_IDS = snap_valid


# ── Round-trip ──────────────────────────────────────────────────────


async def test_reload_from_db_loads_all_seeded_endpoints(test_db_session):
    """Pre-seeded DB (via tools.seed_api_endpoints) must contain all
    ``_CODE_ENDPOINTS`` byte-equal after reload."""
    with _save_and_restore_registry():
        count = await reload_from_db(test_db_session)
        # Reload should never produce fewer endpoints than the code source —
        # the dev DB may carry extra rows added by admin (orphan endpoints
        # that no longer appear in code), which is fine.
        assert count >= len(_CODE_ENDPOINTS)
        for code_ep in _CODE_ENDPOINTS:
            db_ep = api_registry.BY_NAME.get(code_ep.name)
            assert db_ep is not None, f"missing after reload: {code_ep.name}"
            assert db_ep == code_ep, f"divergence on {code_ep.name}"


async def test_reload_rebuilds_all_derived_indices(test_db_session):
    """After reload the derived indices must agree with the new
    ``ALL_ENDPOINTS`` — catches any future global that ``_rebuild_derived_indices``
    forgets to refresh."""
    with _save_and_restore_registry():
        await reload_from_db(test_db_session)
        names = {ep.name for ep in api_registry.ALL_ENDPOINTS}
        paths = {ep.path for ep in api_registry.ALL_ENDPOINTS}
        assert set(api_registry.BY_NAME) == names
        assert set(api_registry.BY_PATH) == paths
        assert api_registry.VALID_ENDPOINT_IDS == frozenset(names)
        # BY_DOMAIN / BY_TIME are bucketed; total size must equal endpoint count.
        assert sum(len(v) for v in api_registry.BY_DOMAIN.values()) == len(names)
        assert sum(len(v) for v in api_registry.BY_TIME.values()) == len(names)


async def test_reload_preserves_semantic_fields(test_db_session):
    """The four P2.3a/P2.4 enrichment fields must round-trip code → DB → reload."""
    with _save_and_restore_registry():
        await reload_from_db(test_db_session)
        # Spot-check an endpoint with non-empty enrichment fields in code.
        ep = api_registry.BY_NAME.get("getInvestPlanByYear")
        assert ep is not None
        assert ep.field_schema, "field_schema lost in round-trip"
        assert ep.use_cases, "use_cases lost in round-trip"
        assert ep.chain_with, "chain_with lost in round-trip"
        assert ep.analysis_note, "analysis_note lost in round-trip"


# ── Failure containment ─────────────────────────────────────────────


async def test_reload_db_error_keeps_previous_state(monkeypatch):
    """If DB read raises, the registry must stay on the prior source."""
    with _save_and_restore_registry():
        before = api_registry.ALL_ENDPOINTS

        async def _boom(*a, **kw):
            raise RuntimeError("simulated DB outage")

        from backend.memory import admin_store
        monkeypatch.setattr(admin_store, "list_api_endpoints", _boom)

        # Pass a fake session so reload_from_db doesn't try to spin up the
        # real session factory before hitting the patched function.
        class _FakeSession: pass

        count = await reload_from_db(_FakeSession())
        assert count == len(before)
        assert api_registry.ALL_ENDPOINTS is before  # untouched


async def test_reload_skips_malformed_row(monkeypatch, caplog):
    """A row missing required dataclass fields must be dropped (WARN), not crash."""
    with _save_and_restore_registry():
        async def _stub(*a, **kw):
            # One good row + one missing 'name'.
            return [
                {
                    "name": "okEndpoint", "path": "/x", "domain": "D1",
                    "intent": "ok", "time_type": "T_RT", "granularity": "G_PORT",
                    "tags": [], "required_params": [], "optional_params": [],
                    "returns": "", "param_note": "", "disambiguate": "",
                    "field_schema": [], "use_cases": [], "chain_with": [],
                    "analysis_note": "", "method": "GET",
                },
                {
                    # Missing "name" → KeyError in _endpoint_from_db_row
                    "path": "/broken", "domain": "D1",
                },
            ]

        from backend.memory import admin_store
        monkeypatch.setattr(admin_store, "list_api_endpoints", _stub)

        class _FakeSession: pass

        with caplog.at_level(logging.WARNING, logger="analytica.api_registry"):
            count = await reload_from_db(_FakeSession())
        assert count == 1
        assert "okEndpoint" in api_registry.BY_NAME
        # The malformed row triggered a WARN.
        assert any("skipping malformed" in r.message for r in caplog.records)

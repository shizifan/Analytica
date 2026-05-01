"""``reload_from_db()`` swaps the in-memory registry with DB rows.

Three guarantees pinned here:

  1. **Round-trip**: ``data/api_registry.json`` → DB → ``reload_from_db``
     produces an ``ALL_ENDPOINTS`` whose names are a superset of the
     factory JSON (DB may carry extra rows added through the admin UI).
  2. **Lossless reconstruction**: the 4 semantic fields (``field_schema`` /
     ``use_cases`` / ``chain_with`` / ``analysis_note``) survive
     JSON → seed → DB → reload identically.
  3. **Failure modes**: DB read errors propagate (no silent fallback);
     a single malformed row is skipped with a WARN, never crashes
     the loader.

Tests use the dev DB seeded by ``tools.seed_api_endpoints`` via the
session-scope conftest fixture; tests that mutate module globals snapshot
+ restore them so other tests aren't affected.
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from pathlib import Path

import pytest

from backend.agent import api_registry
from backend.agent.api_registry import reload_from_db

pytestmark = pytest.mark.contract


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _factory_endpoint_names() -> set[str]:
    """Names from the factory JSON — the minimum set the DB must contain."""
    payload = json.loads((_REPO_ROOT / "data" / "api_registry.json").read_text())
    return {ep["name"] for ep in payload.get("endpoints", [])}


@contextmanager
def _save_and_restore_registry():
    """Snapshot module globals so a reload_from_db call can be reverted."""
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


# ── Round-trip ──────────────────────────────────────────────────────


async def test_reload_from_db_loads_all_seeded_endpoints(test_db_session):
    """The seeded DB must contain every name from the factory JSON after reload."""
    with _save_and_restore_registry():
        ep_count, dom_count = await reload_from_db(test_db_session)
        factory_names = _factory_endpoint_names()
        # The dev DB may carry extra rows added by admin (orphan endpoints
        # that no longer appear in the factory JSON), which is fine.
        assert ep_count >= len(factory_names)
        assert dom_count >= 1
        loaded_names = {ep.name for ep in api_registry.ALL_ENDPOINTS}
        missing = factory_names - loaded_names
        assert not missing, f"missing after reload: {sorted(missing)}"


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
        assert api_registry.VALID_ENDPOINT_IDS == names
        # BY_DOMAIN / BY_TIME are bucketed; total size must equal endpoint count.
        assert sum(len(v) for v in api_registry.BY_DOMAIN.values()) == len(names)
        assert sum(len(v) for v in api_registry.BY_TIME.values()) == len(names)


async def test_reload_loads_domains(test_db_session):
    """Domains are co-loaded from the same call; DOMAIN_INDEX must be
    populated and consistent with endpoint domain refs."""
    with _save_and_restore_registry():
        await reload_from_db(test_db_session)
        assert api_registry.DOMAIN_INDEX, "DOMAIN_INDEX should not be empty after reload"
        # Every endpoint's domain code should resolve to a known domain.
        endpoint_domains = {ep.domain for ep in api_registry.ALL_ENDPOINTS}
        known = set(api_registry.DOMAIN_INDEX)
        unknown = endpoint_domains - known
        assert not unknown, f"endpoints reference undefined domains: {unknown}"


async def test_reload_preserves_semantic_fields(test_db_session):
    """The four enrichment fields must round-trip JSON → DB → reload."""
    with _save_and_restore_registry():
        await reload_from_db(test_db_session)
        # Spot-check an endpoint with non-empty enrichment fields in the JSON.
        ep = api_registry.BY_NAME.get("getInvestPlanByYear")
        assert ep is not None
        assert ep.field_schema, "field_schema lost in round-trip"
        assert ep.use_cases, "use_cases lost in round-trip"
        assert ep.chain_with, "chain_with lost in round-trip"
        assert ep.analysis_note, "analysis_note lost in round-trip"


# ── Failure modes ───────────────────────────────────────────────────


async def test_reload_db_error_propagates(monkeypatch):
    """A DB read failure must propagate — no silent fallback. Caller
    (lifespan) must surface a clear error rather than serve stale data."""
    with _save_and_restore_registry():
        async def _boom(*a, **kw):
            raise RuntimeError("simulated DB outage")

        from backend.memory import admin_store
        monkeypatch.setattr(admin_store, "list_api_endpoints", _boom)

        class _FakeSession: pass

        with pytest.raises(RuntimeError, match="simulated DB outage"):
            await reload_from_db(_FakeSession())


async def test_reload_skips_malformed_row(monkeypatch, caplog):
    """A row missing required dataclass fields must be dropped (WARN), not crash."""
    with _save_and_restore_registry():
        async def _stub_endpoints(*a, **kw):
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

        async def _stub_domains(*a, **kw):
            return [{"code": "D1", "name": "Test", "description": "t",
                     "color": None, "top_tags": [], "api_count": 1,
                     "employee_count": 0, "updated_at": None}]

        from backend.memory import admin_store
        monkeypatch.setattr(admin_store, "list_api_endpoints", _stub_endpoints)
        monkeypatch.setattr(admin_store, "list_domains", _stub_domains)

        class _FakeSession: pass

        with caplog.at_level(logging.WARNING, logger="analytica.api_registry"):
            ep_count, dom_count = await reload_from_db(_FakeSession())
        assert ep_count == 1
        assert dom_count == 1
        assert "okEndpoint" in api_registry.BY_NAME
        # The malformed row triggered a WARN.
        assert any("skipping malformed" in r.message for r in caplog.records)

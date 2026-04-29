"""P2.4-6 — ``db`` / ``dual_db`` source modes & lifespan hook.

Three guarantees:

  1. ``_resolve_source`` returns the code source for ``db`` / ``dual_db``
     at module init (deferring DB load to the lifespan hook), so import
     paths remain valid even with no DB connection.
  2. ``lifespan_apply_source`` is a no-op when the FF is code/file/dual
     and triggers ``reload_from_db`` only for db / dual_db.
  3. ``_diff_dual_db`` flags divergences with the ``[dual_db]`` prefix
     (distinct from ``[dual]`` so log search remains unambiguous).
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest

from backend.agent import api_registry
from backend.agent.api_registry import (
    _CODE_DOMAIN_INDEX,
    _CODE_ENDPOINTS,
    _diff_dual_db,
    _resolve_source,
    lifespan_apply_source,
)

pytestmark = pytest.mark.contract


@contextmanager
def _save_and_restore_registry():
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


# ── _resolve_source: db / dual_db at module init ────────────────────


def test_db_source_defers_to_lifespan(caplog):
    """At sync init, ``db`` mode must return code (not crash on no DB)."""
    with caplog.at_level(logging.INFO, logger="analytica.api_registry"):
        domains, endpoints = _resolve_source("db")
    assert endpoints is _CODE_ENDPOINTS
    assert domains is _CODE_DOMAIN_INDEX
    assert any("deferring DB load" in r.message for r in caplog.records)


def test_dual_db_source_defers_to_lifespan(caplog):
    with caplog.at_level(logging.INFO, logger="analytica.api_registry"):
        domains, endpoints = _resolve_source("dual_db")
    assert endpoints is _CODE_ENDPOINTS
    assert domains is _CODE_DOMAIN_INDEX
    assert any("deferring DB load" in r.message for r in caplog.records)


# ── lifespan_apply_source ───────────────────────────────────────────


async def test_lifespan_is_noop_for_non_db_sources(monkeypatch):
    """``code`` / ``file`` / ``dual`` must not trigger reload_from_db."""
    fake_reload = AsyncMock(return_value=0)
    monkeypatch.setattr(api_registry, "reload_from_db", fake_reload)
    for src in ("code", "file", "dual"):
        monkeypatch.setattr(
            api_registry, "get_settings", lambda: type("S", (), {"FF_API_REGISTRY_SOURCE": src})(),
            raising=False,
        )
        # The function imports settings via `from backend.config import get_settings`
        # — patch that path instead.
        from backend.config import get_settings as _real
        monkeypatch.setattr(
            "backend.config.get_settings",
            lambda: type("S", (), {"FF_API_REGISTRY_SOURCE": src})(),
        )
        await lifespan_apply_source()
    assert fake_reload.await_count == 0


async def test_lifespan_calls_reload_for_db_source(monkeypatch):
    fake_reload = AsyncMock(return_value=42)
    monkeypatch.setattr(api_registry, "reload_from_db", fake_reload)
    monkeypatch.setattr(
        "backend.config.get_settings",
        lambda: type("S", (), {"FF_API_REGISTRY_SOURCE": "db"})(),
    )
    await lifespan_apply_source()
    assert fake_reload.await_count == 1


async def test_lifespan_calls_reload_and_diff_for_dual_db(monkeypatch):
    fake_reload = AsyncMock(return_value=42)
    fake_diff = AsyncMock()
    # _diff_dual_db is sync; AsyncMock won't be awaited so use a plain Mock-like.
    calls = {"diff": 0}

    def fake_diff_sync():
        calls["diff"] += 1

    monkeypatch.setattr(api_registry, "reload_from_db", fake_reload)
    monkeypatch.setattr(api_registry, "_diff_dual_db", fake_diff_sync)
    monkeypatch.setattr(
        "backend.config.get_settings",
        lambda: type("S", (), {"FF_API_REGISTRY_SOURCE": "dual_db"})(),
    )
    await lifespan_apply_source()
    assert fake_reload.await_count == 1
    assert calls["diff"] == 1


# ── _diff_dual_db logs ──────────────────────────────────────────────


def test_diff_dual_db_quiet_when_db_matches_code(caplog):
    """No drift expected when the registry hasn't been swapped (current
    state == code). Pins the happy-path baseline."""
    with caplog.at_level(logging.WARNING, logger="analytica.api_registry"):
        _diff_dual_db()
    dual_db_warnings = [r for r in caplog.records if "[dual_db]" in r.message]
    assert dual_db_warnings == []


def test_diff_dual_db_logs_endpoint_only_in_db(caplog):
    """Inject an extra endpoint into BY_NAME → should surface as DB-only WARN."""
    with _save_and_restore_registry():
        extra = api_registry.ApiEndpoint(
            name="testOnlyInDb",
            path="/api/test/onlyInDb",
            domain="D1", intent="db-only fixture",
            time="T_RT", granularity="G_PORT",
            tags=("test",), required=(), optional=(),
            param_note="", returns="", disambiguate="",
        )
        api_registry.BY_NAME[extra.name] = extra

        with caplog.at_level(logging.WARNING, logger="analytica.api_registry"):
            _diff_dual_db()
    matched = [
        r for r in caplog.records
        if "endpoints only in DB" in r.message and "testOnlyInDb" in r.message
    ]
    assert matched, [r.message for r in caplog.records]


def test_diff_dual_db_uses_distinct_log_prefix(caplog):
    """``[dual]`` and ``[dual_db]`` must be distinct so log search isn't
    ambiguous between P2.2 and P2.4 modes."""
    with _save_and_restore_registry():
        # Remove an endpoint to trigger "only in code" warning.
        first = _CODE_ENDPOINTS[0]
        api_registry.BY_NAME.pop(first.name, None)
        with caplog.at_level(logging.WARNING, logger="analytica.api_registry"):
            _diff_dual_db()
    bare_dual = [r for r in caplog.records if "[dual]" in r.message and "[dual_db]" not in r.message]
    has_dual_db = [r for r in caplog.records if "[dual_db]" in r.message]
    assert not bare_dual
    assert has_dual_db

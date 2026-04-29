"""P2.2 — ``FF_API_REGISTRY_SOURCE`` dispatch contract.

Pins the runtime behaviour of ``_resolve_source(source)``:

  - ``code``: returns the inline ``_CODE_*`` references.
  - ``file``: loads ``data/api_registry.json`` and returns its content.
  - ``dual``: loads file, runs ``_diff_dual`` (WARN log on divergence),
    but returns ``_CODE_*`` so served behaviour is unchanged.
  - Unknown / missing-file / parse-failure: WARN + fall back to ``code``.

Module-init side effects (assigning ``ALL_ENDPOINTS`` etc.) are exercised
indirectly via ``_apply_source_override``; for direct dispatch testing we
call ``_resolve_source(source)`` with explicit values so test isolation
doesn't depend on env var ordering.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from backend.agent import api_registry
from backend.agent.api_registry import (
    _CODE_DOMAIN_INDEX,
    _CODE_ENDPOINTS,
    _diff_dual,
    _resolve_source,
    load_from_json,
    serialize_to_dict,
)

pytestmark = pytest.mark.contract


# ── Pure dispatcher behaviour ────────────────────────────────────────


def test_code_source_returns_inline_references():
    domains, endpoints = _resolve_source("code")
    assert endpoints is _CODE_ENDPOINTS
    assert domains is _CODE_DOMAIN_INDEX


def test_file_source_returns_file_content_equal_to_code():
    domains, endpoints = _resolve_source("file")
    # File is the exported snapshot of code, so they must match by value.
    assert endpoints == _CODE_ENDPOINTS
    assert domains == _CODE_DOMAIN_INDEX
    # But not the same object — file mode reconstructs new dataclasses.
    assert endpoints is not _CODE_ENDPOINTS


def test_dual_source_returns_code_as_primary(caplog):
    """Dual mode keeps code primary so served behaviour is unchanged."""
    with caplog.at_level(logging.WARNING, logger="analytica.api_registry"):
        domains, endpoints = _resolve_source("dual")
    assert endpoints is _CODE_ENDPOINTS
    assert domains is _CODE_DOMAIN_INDEX
    # When file matches code (the freshness contract guarantees this),
    # dual mode should not log any divergence.
    divergence_logs = [r for r in caplog.records if "[dual]" in r.message]
    assert divergence_logs == [], (
        f"unexpected divergence in dual mode: {[r.message for r in divergence_logs]}"
    )


def test_unknown_source_falls_back_to_code(caplog):
    with caplog.at_level(logging.WARNING, logger="analytica.api_registry"):
        domains, endpoints = _resolve_source("unknown_value")
    assert endpoints is _CODE_ENDPOINTS
    assert any("unknown FF_API_REGISTRY_SOURCE" in r.message for r in caplog.records)


def test_missing_file_falls_back_to_code(monkeypatch, caplog, tmp_path):
    """When source=file but the JSON is absent, fall back gracefully."""
    fake_path = tmp_path / "nonexistent.json"
    monkeypatch.setattr(api_registry, "_registry_json_path", lambda: fake_path)
    with caplog.at_level(logging.WARNING, logger="analytica.api_registry"):
        domains, endpoints = _resolve_source("file")
    assert endpoints is _CODE_ENDPOINTS
    assert any("missing" in r.message for r in caplog.records)


def test_parse_failure_falls_back_to_code(monkeypatch, caplog, tmp_path):
    """Corrupt JSON must not crash module init."""
    bad_path = tmp_path / "broken.json"
    bad_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(api_registry, "_registry_json_path", lambda: bad_path)
    with caplog.at_level(logging.WARNING, logger="analytica.api_registry"):
        domains, endpoints = _resolve_source("file")
    assert endpoints is _CODE_ENDPOINTS
    assert any("failed to load" in r.message for r in caplog.records)


# ── Diff inspector ──────────────────────────────────────────────────


def test_diff_dual_no_warnings_when_file_matches_code(caplog):
    """The freshness contract guarantees parity, so this is the
    happy-path baseline (no WARN expected)."""
    payload = serialize_to_dict()
    file_domains, file_endpoints = load_from_json(payload)
    with caplog.at_level(logging.WARNING, logger="analytica.api_registry"):
        _diff_dual(file_domains, file_endpoints)
    dual_warnings = [r for r in caplog.records if "[dual]" in r.message]
    assert dual_warnings == []


def test_diff_dual_logs_endpoint_only_in_file(caplog):
    """An endpoint present only in the file source must surface as WARN."""
    extra = api_registry.ApiEndpoint(
        name="testOnlyInFile",
        path="/api/test/onlyInFile",
        domain="D1",
        intent="fixture-only endpoint, never authored in code",
        time="T_RT",
        granularity="G_PORT",
        tags=("test",),
        required=(),
        optional=(),
        param_note="",
        returns="",
        disambiguate="",
    )
    file_endpoints = _CODE_ENDPOINTS + (extra,)
    with caplog.at_level(logging.WARNING, logger="analytica.api_registry"):
        _diff_dual(_CODE_DOMAIN_INDEX, file_endpoints)
    matched = [
        r for r in caplog.records
        if "endpoints only in file" in r.message and "testOnlyInFile" in r.message
    ]
    assert matched, [r.message for r in caplog.records]


def test_diff_dual_logs_field_divergence(caplog):
    """Same endpoint name with a changed field must surface as WARN."""
    first, *rest = list(_CODE_ENDPOINTS)
    drifted_first = api_registry.ApiEndpoint(
        **{**first.__dict__, "intent": "REWRITTEN INTENT (test)"},
    )
    drifted_endpoints = (drifted_first, *rest)
    with caplog.at_level(logging.WARNING, logger="analytica.api_registry"):
        _diff_dual(_CODE_DOMAIN_INDEX, drifted_endpoints)
    matched = [
        r for r in caplog.records
        if "field divergence" in r.message and first.name in r.message
    ]
    assert matched, [r.message for r in caplog.records]


# ── Module-init exposed state ───────────────────────────────────────


def test_default_module_state_uses_code_source():
    """At import time the registry exposes the inline ``_CODE_*`` data.

    Catches any future change that would silently switch the default
    source for production runtime.
    """
    assert api_registry.ALL_ENDPOINTS is _CODE_ENDPOINTS
    assert api_registry.DOMAIN_INDEX is _CODE_DOMAIN_INDEX
    # And the derived indices must agree.
    assert set(api_registry.BY_NAME) == {ep.name for ep in _CODE_ENDPOINTS}

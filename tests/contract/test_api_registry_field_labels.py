"""``ApiEndpoint.field_schema`` 4-element shape contract.

Three-element rows ``(name, type, desc)`` remain the historical baseline.
Adding a 4th element ``label_zh`` lets a single endpoint override the
Chinese display name for a column. This file pins the schema mechanics
so downstream label-resolution code has a stable contract to build on.

Round-trip equivalence (factory JSON → DB → reload) is covered by
``test_api_registry_reload_from_db.test_reload_preserves_semantic_fields``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.agent.api_registry import ApiEndpoint

pytestmark = pytest.mark.contract


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_endpoint(field_schema):
    """Test factory — minimum required fields plus a custom field_schema."""
    return ApiEndpoint(
        name="testFixtureEndpoint",
        path="/api/test/fixture",
        domain="D1",
        intent="fixture endpoint for label_for tests",
        time="T_RT",
        granularity="G_PORT",
        tags=("test",),
        required=(),
        optional=(),
        param_note="",
        returns="",
        disambiguate="",
        field_schema=field_schema,
    )


def test_label_for_returns_label_zh_when_present():
    ep = _make_endpoint((
        ("qty", "int", "throughput in tons", "吨吞吐量(测试覆写)"),
        ("dateMonth", "str", "month YYYY-MM"),  # 3-elt, no label
    ))
    assert ep.label_for("qty") == "吨吞吐量(测试覆写)"
    # 3-element row → no per-endpoint label
    assert ep.label_for("dateMonth") is None


def test_label_for_returns_none_for_unknown_column():
    ep = _make_endpoint((
        ("qty", "int", "throughput in tons", "吨吞吐量"),
    ))
    assert ep.label_for("not_a_real_column") is None


def test_label_for_treats_empty_label_as_missing():
    """An empty 4th element must NOT override the global fallback."""
    ep = _make_endpoint((
        ("qty", "int", "throughput in tons", ""),
    ))
    assert ep.label_for("qty") is None


def test_factory_json_field_schema_rows_are_3_or_4_elements():
    """All checked-in field_schema entries in the factory JSON must be
    3 or 4 elements long. Catches accidental 2-element or 5-element rows
    introduced during manual edits to data/api_registry.json.
    """
    payload = json.loads((_REPO_ROOT / "data" / "api_registry.json").read_text())
    for ep in payload.get("endpoints", []):
        for row in ep.get("field_schema") or []:
            assert len(row) in (3, 4), (
                f"endpoint {ep['name']!r} has malformed field_schema row: {row}"
            )

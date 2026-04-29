"""P2.3a — ``ApiEndpoint.field_schema`` 4-element shape contract.

Three-element rows ``(name, type, desc)`` remain the historical baseline.
Adding a 4th element ``label_zh`` lets a single endpoint override the
Chinese display name for a column. P2.3b will thread this into the report
and chart label-resolution path; this file pins the schema mechanics so
the wiring step has a stable contract to build on.
"""
from __future__ import annotations

import pytest

from backend.agent.api_registry import (
    ApiEndpoint,
    load_from_json,
    serialize_to_dict,
)

pytestmark = pytest.mark.contract


def _make_endpoint(field_schema):
    """Test factory — minimum required fields plus a custom field_schema."""
    return ApiEndpoint(
        name="testFixtureEndpoint",
        path="/api/test/fixture",
        domain="D1",
        intent="fixture endpoint for label_for / round-trip tests",
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


def test_three_element_field_schema_still_loads():
    """Backward-compat: existing JSON with 3-element rows must keep working."""
    payload = {
        "domains": {},
        "endpoints": [{
            "name": "ep3",
            "path": "/x", "domain": "D1", "intent": "i", "time": "T_RT",
            "granularity": "G_PORT", "tags": [], "required": [], "optional": [],
            "param_note": "", "returns": "", "disambiguate": "",
            "field_schema": [["qty", "int", "throughput"]],
            "use_cases": [], "chain_with": [], "analysis_note": "", "method": "GET",
        }],
    }
    _, endpoints = load_from_json(payload)
    assert len(endpoints[0].field_schema) == 1
    row = endpoints[0].field_schema[0]
    assert row == ("qty", "int", "throughput")
    assert endpoints[0].label_for("qty") is None


def test_four_element_field_schema_round_trips():
    """Serialize → JSON → load_from_json preserves the 4th element."""
    original = (
        ("qty", "int", "throughput in tons", "吨吞吐量"),
        ("dateMonth", "str", "month YYYY-MM"),  # 3-elt mixed in
    )
    fixture = _make_endpoint(original)
    payload = {
        "domains": {},
        "endpoints": [{
            "name": fixture.name, "path": fixture.path, "domain": fixture.domain,
            "intent": fixture.intent, "time": fixture.time,
            "granularity": fixture.granularity, "tags": list(fixture.tags),
            "required": list(fixture.required), "optional": list(fixture.optional),
            "param_note": fixture.param_note, "returns": fixture.returns,
            "disambiguate": fixture.disambiguate,
            "field_schema": [list(row) for row in fixture.field_schema],
            "use_cases": list(fixture.use_cases),
            "chain_with": list(fixture.chain_with),
            "analysis_note": fixture.analysis_note, "method": fixture.method,
        }],
    }
    _, endpoints = load_from_json(payload)
    rebuilt = endpoints[0]
    assert rebuilt.field_schema == original
    assert rebuilt.label_for("qty") == "吨吞吐量"
    assert rebuilt.label_for("dateMonth") is None


def test_serialize_emits_four_element_rows_as_lists():
    """JSON output must store 4-elt rows as lists of 4 (not silently truncate)."""
    # We don't mutate ALL_ENDPOINTS; instead exercise the serialize helper
    # path indirectly by checking that 4-elt data survives _to_jsonable.
    from backend.agent.api_registry import _to_jsonable
    out = _to_jsonable((("qty", "int", "throughput", "吨吞吐量"),))
    assert out == [["qty", "int", "throughput", "吨吞吐量"]]


def test_existing_endpoints_have_three_or_four_element_rows_only():
    """All checked-in field_schema entries must be 3 or 4 elements long.

    Catches accidental 2-element or 5-element rows introduced during edits.
    """
    payload = serialize_to_dict()
    for ep in payload["endpoints"]:
        for row in ep.get("field_schema", ()):
            assert len(row) in (3, 4), (
                f"endpoint {ep['name']!r} has malformed field_schema row: {row}"
            )

"""P2.3b — endpoint-aware label resolution & DataFrame rename wiring.

End-to-end check that an endpoint's per-column ``label_zh`` (P2.3a's 4th
field_schema element) actually flows through to the rendered column header.

Validates:
  - ``resolve_col_label`` precedence: per-endpoint > global > raw passthrough.
  - ``DataFrameItem.endpoint_name`` propagates through ``normalize_dataframe_item``.
  - ``_extract_items`` reads ``endpoint`` from ``ToolOutput.metadata``.
"""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from backend.agent import api_registry
from backend.agent.api_registry import ApiEndpoint
from backend.tools._field_labels import COLUMN_LABELS, resolve_col_label
from backend.tools.report._content_collector import (
    ChartDataItem,
    DataFrameItem,
    _extract_items,
    normalize_dataframe_item,
)

pytestmark = pytest.mark.contract


# ── resolve_col_label precedence ─────────────────────────────────────


def test_resolve_col_label_falls_back_to_global_without_endpoint():
    # "qty" is in COLUMN_LABELS → should return the global label.
    assert resolve_col_label(None, "qty") == COLUMN_LABELS["qty"]


def test_resolve_col_label_passes_through_unknown_column():
    assert resolve_col_label(None, "totally_unknown") == "totally_unknown"


def test_resolve_col_label_falls_back_when_endpoint_unknown():
    # An endpoint name that doesn't exist in BY_NAME must not crash.
    assert resolve_col_label("nonexistentEndpoint", "qty") == COLUMN_LABELS["qty"]


def test_resolve_col_label_uses_endpoint_override_when_present(monkeypatch):
    """A 4-element field_schema row beats the global map."""
    fixture = ApiEndpoint(
        name="testEndpointForLabel",
        path="/x", domain="D1", intent="i",
        time="T_RT", granularity="G_PORT",
        tags=(), required=(), optional=(),
        param_note="", returns="", disambiguate="",
        field_schema=(
            ("qty", "int", "throughput", "吨吞吐量(端点覆写)"),
        ),
    )
    monkeypatch.setitem(api_registry.BY_NAME, fixture.name, fixture)
    assert resolve_col_label(fixture.name, "qty") == "吨吞吐量(端点覆写)"
    # Cleanup is automatic (monkeypatch restores BY_NAME).


def test_resolve_col_label_falls_back_when_endpoint_has_no_override(monkeypatch):
    """Endpoint with 3-element row only → global label still wins."""
    fixture = ApiEndpoint(
        name="testEndpointNoOverride",
        path="/x", domain="D1", intent="i",
        time="T_RT", granularity="G_PORT",
        tags=(), required=(), optional=(),
        param_note="", returns="", disambiguate="",
        field_schema=(
            ("qty", "int", "throughput"),  # 3-elt; no label_zh
        ),
    )
    monkeypatch.setitem(api_registry.BY_NAME, fixture.name, fixture)
    assert resolve_col_label(fixture.name, "qty") == COLUMN_LABELS["qty"]


# ── DataFrameItem propagation through normalize_dataframe_item ───────


def test_normalize_dataframe_item_preserves_endpoint_name():
    df = pd.DataFrame({"qty": [10, 20, 30]})
    item = DataFrameItem(df=df, source_task="T01", endpoint_name="getThroughputByZone")
    out = normalize_dataframe_item(item)
    assert out.endpoint_name == "getThroughputByZone"


def test_normalize_dataframe_item_renames_via_endpoint_label(monkeypatch):
    """The end-to-end win: DataFrame columns get the endpoint's per-column label."""
    fixture = ApiEndpoint(
        name="testEndpointRender",
        path="/x", domain="D1", intent="i",
        time="T_RT", granularity="G_PORT",
        tags=(), required=(), optional=(),
        param_note="", returns="", disambiguate="",
        field_schema=(
            ("qty", "int", "throughput", "吨位(覆写)"),
        ),
    )
    monkeypatch.setitem(api_registry.BY_NAME, fixture.name, fixture)
    df = pd.DataFrame({"qty": [1, 2, 3]})
    out = normalize_dataframe_item(
        DataFrameItem(df=df, source_task="T01", endpoint_name=fixture.name)
    )
    assert "吨位(覆写)" in out.df.columns
    assert "qty" not in out.df.columns


def test_normalize_dataframe_item_falls_back_to_global_without_endpoint():
    """No endpoint_name → uses global COLUMN_LABELS (existing behaviour)."""
    df = pd.DataFrame({"qty": [1, 2, 3]})
    out = normalize_dataframe_item(DataFrameItem(df=df, source_task="T01"))
    # qty → 吨吞吐量 from global map
    assert COLUMN_LABELS["qty"] in out.df.columns


# ── _extract_items reads ToolOutput.metadata.endpoint ────────────────


class _FakeToolOutput:
    """Minimal stand-in for backend.tools.base.ToolOutput.

    The collector only reads ``status``, ``data``, and ``metadata`` via
    ``getattr``; we don't depend on the full pydantic model here."""

    def __init__(self, data, metadata=None, status="success"):
        self.data = data
        self.metadata = metadata or {}
        self.status = status


def test_extract_items_captures_endpoint_from_metadata():
    df = pd.DataFrame({"qty": [1, 2, 3]})
    context = {
        "T01": _FakeToolOutput(df, metadata={"endpoint": "getMyApi"}),
    }
    items, _ = _extract_items(context, task_order=["T01"])
    assert len(items) == 1
    assert isinstance(items[0], DataFrameItem)
    assert items[0].endpoint_name == "getMyApi"


def test_extract_items_chart_item_captures_endpoint():
    chart_data = {"series": [{"data": [1, 2]}], "title": "x"}
    context = {
        "T02": _FakeToolOutput(chart_data, metadata={"endpoint": "getChartSrc"}),
    }
    items, _ = _extract_items(context, task_order=["T02"])
    chart_items = [i for i in items if isinstance(i, ChartDataItem)]
    assert len(chart_items) == 1
    assert chart_items[0].endpoint_name == "getChartSrc"


def test_extract_items_endpoint_name_none_when_metadata_missing():
    df = pd.DataFrame({"qty": [1, 2, 3]})
    context = {
        "T03": _FakeToolOutput(df, metadata={}),  # no endpoint key
    }
    items, _ = _extract_items(context, task_order=["T03"])
    assert items[0].endpoint_name is None

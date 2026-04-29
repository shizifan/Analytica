"""P2.3b extension — chat task-result preview must use endpoint-aware
Chinese column labels (matching the report rendering path).

The DataFrame preview shown in the chat bubble is built by
``_build_task_results_payload`` in ``backend.agent.execution``. Without
translation, users see raw English column names like ``assetTypeName``
even though the report path renders ``资产类型`` correctly. This file
pins the translation behaviour:

  * api_fetch produces a ToolOutput with ``metadata['endpoint'] = <name>``;
    columns get the per-endpoint label (4-elt field_schema row) when set,
    falling back to ``COLUMN_LABELS``.
  * Tools without an ``endpoint`` metadata (analysis / chart outputs) fall
    back to the global label, never crash.
  * Unmapped columns pass through untouched.
"""
from __future__ import annotations

import pandas as pd
import pytest

from backend.agent.execution import _build_task_results_payload
from backend.models.schemas import TaskItem
from backend.tools.base import ToolOutput
from backend.tools._field_labels import COLUMN_LABELS

pytestmark = pytest.mark.contract


def _output_with_df(df: pd.DataFrame, endpoint: str | None = None) -> ToolOutput:
    metadata = {"endpoint": endpoint} if endpoint else {}
    return ToolOutput(
        tool_id="tool_api_fetch",
        status="success",
        output_type="dataframe",
        data=df,
        metadata=metadata,
    )


def _make_task(task_id: str = "T01") -> TaskItem:
    return TaskItem(
        task_id=task_id,
        name="fixture",
        type="data_fetch",
        tool="tool_api_fetch",
        depends_on=[],
        params={"endpoint_id": "getCategoryAnalysis"},
    )


def test_columns_translated_via_global_labels_when_metadata_present():
    df = pd.DataFrame({
        "assetTypeName": ["设备"],
        "typeName": ["实物资产数"],
        "num": [10],
    })
    task = _make_task()
    payload = _build_task_results_payload(
        tasks=[task],
        execution_context={"T01": _output_with_df(df, endpoint="getCategoryAnalysis")},
        task_statuses={"T01": "done"},
    )
    cols = payload["tasks"][0]["data"]["columns"]
    # All three are present in COLUMN_LABELS → expect Chinese labels.
    assert cols == [
        COLUMN_LABELS["assetTypeName"],
        COLUMN_LABELS["typeName"],
        COLUMN_LABELS["num"],
    ]


def test_columns_translated_via_global_labels_without_endpoint_metadata():
    """Tools other than api_fetch (no ``metadata.endpoint``) still get the
    global label translation — chat preview shouldn't degrade for analysis
    outputs."""
    df = pd.DataFrame({"qty": [10, 20], "rate": [0.1, 0.2]})
    payload = _build_task_results_payload(
        tasks=[_make_task()],
        execution_context={"T01": _output_with_df(df, endpoint=None)},
        task_statuses={"T01": "done"},
    )
    cols = payload["tasks"][0]["data"]["columns"]
    assert cols == [COLUMN_LABELS["qty"], COLUMN_LABELS["rate"]]


def test_unknown_column_passes_through_unchanged():
    df = pd.DataFrame({"someUnknownField": [1, 2]})
    payload = _build_task_results_payload(
        tasks=[_make_task()],
        execution_context={"T01": _output_with_df(df, endpoint="getCategoryAnalysis")},
        task_statuses={"T01": "done"},
    )
    assert payload["tasks"][0]["data"]["columns"] == ["someUnknownField"]


def test_endpoint_label_for_overrides_global(monkeypatch):
    """If the endpoint sets a per-column ``label_zh`` via P2.3a 4-element
    field_schema row, that override beats the global label."""
    from backend.agent import api_registry

    fixture = api_registry.ApiEndpoint(
        name="testOverrideEp",
        path="/x", domain="D1", intent="i",
        time="T_RT", granularity="G_PORT",
        tags=(), required=(), optional=(),
        param_note="", returns="", disambiguate="",
        field_schema=(
            ("qty", "int", "throughput", "吨吞吐量(端点覆写)"),
        ),
    )
    monkeypatch.setitem(api_registry.BY_NAME, fixture.name, fixture)

    df = pd.DataFrame({"qty": [1, 2]})
    payload = _build_task_results_payload(
        tasks=[_make_task()],
        execution_context={"T01": _output_with_df(df, endpoint=fixture.name)},
        task_statuses={"T01": "done"},
    )
    assert payload["tasks"][0]["data"]["columns"] == ["吨吞吐量(端点覆写)"]

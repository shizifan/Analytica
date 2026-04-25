"""Regression: chart param parser must survive LLM-generated malformed shapes."""
from __future__ import annotations

import pandas as pd

from backend.tools.visualization._config_parser import (
    apply_row_filter,
    parse_chart_params,
)


def test_filter_coerces_string_to_empty_dict():
    """Bug 2026-04-21: LLM generated ``"filter": "port=全港"`` (a string)
    which crashed the line chart tool with
    ``'str' object has no attribute 'items'``."""
    parsed = parse_chart_params({
        "config": {"filter": "port=全港"},
    })
    assert parsed["filter"] == {}


def test_apply_row_filter_ignores_string_input():
    """Defense in depth — tools may bypass parse_chart_params."""
    df = pd.DataFrame({"a": [1, 2, 3]})
    # String input must not crash — just return df unchanged.
    result = apply_row_filter(df, "port=全港")
    assert result.equals(df)
    # None, list, int — all coerced to no-op.
    assert apply_row_filter(df, None).equals(df)
    assert apply_row_filter(df, []).equals(df)
    assert apply_row_filter(df, 0).equals(df)


def test_apply_row_filter_happy_path_still_works():
    df = pd.DataFrame({"port": ["A", "B", "A"], "qty": [1, 2, 3]})
    out = apply_row_filter(df, {"port": "A"})
    assert list(out["qty"]) == [1, 3]


def test_left_right_y_coerced_to_none():
    parsed = parse_chart_params({
        "config": {
            "left_y": "not a dict",
            "right_y": 123,
        },
    })
    assert parsed["left_y"] is None
    assert parsed["right_y"] is None


def test_series_coerced_from_dict_and_scalar():
    # Single-dict shape normalised to one-element list
    parsed = parse_chart_params({"config": {"series": {"name": "A"}}})
    assert parsed["series"] == [{"name": "A"}]
    # Garbage scalar normalised to []
    parsed = parse_chart_params({"config": {"series": "not-a-list"}})
    assert parsed["series"] == []


def test_axis_spec_dict_passthrough():
    """Single-series dict shape should be preserved unchanged."""
    parsed = parse_chart_params({
        "config": {
            "left_y": {"label": "吞吐量", "source": "T001", "y_field": "qty"},
        },
    })
    assert parsed["left_y"] == {"label": "吞吐量", "source": "T001", "y_field": "qty"}


def test_axis_spec_list_normalised_to_series_wrapper():
    """Bug 2026-04-25: LLM emitted left_y/right_y as list[dict] (multi-series
    sharing one axis). Previously the parser dropped them entirely. Now the
    list is wrapped as ``{label, series: [...]}`` so the axis renders
    multiple series correctly."""
    parsed = parse_chart_params({
        "config": {
            "left_y": [
                {"label": "利用率", "source": "T011", "y_field": "usageRate"},
                {"label": "完好率", "source": "T012", "y_field": "serviceableRate"},
            ],
            "right_y": [
                {"label": "台时效率", "source": "T013", "y_field": "machineHourRate"},
            ],
        },
    })
    assert parsed["left_y"]["label"] == "利用率 / 完好率"
    assert len(parsed["left_y"]["series"]) == 2
    assert parsed["left_y"]["series"][0]["source"] == "T011"
    assert parsed["right_y"]["label"] == "台时效率"
    assert len(parsed["right_y"]["series"]) == 1


def test_axis_spec_unknown_shape_drops_with_warning():
    """Garbage input (string / int / mixed list) must drop to None — never raise."""
    parsed = parse_chart_params({
        "config": {
            "left_y": "not-a-dict",
            "right_y": 42,
        },
    })
    assert parsed["left_y"] is None
    assert parsed["right_y"] is None


def test_axis_spec_expand_subspecs_helper():
    """`_expand_axis_subspecs` must inherit the wrapper-level label as a
    fallback when a sub-spec omits its own label."""
    from backend.tools.visualization.chart_line import _expand_axis_subspecs

    spec = {"label": "默认", "series": [
        {"source": "T1", "y_field": "x"},
        {"label": "覆盖", "source": "T2", "y_field": "y"},
    ]}
    expanded = _expand_axis_subspecs(spec)
    assert len(expanded) == 2
    assert expanded[0]["label"] == "默认"
    assert expanded[1]["label"] == "覆盖"

    # Single-dict shape → 1-item list
    assert _expand_axis_subspecs({"source": "T1", "y_field": "x"}) == [{"source": "T1", "y_field": "x"}]
    # None / non-dict → empty
    assert _expand_axis_subspecs(None) == []
    assert _expand_axis_subspecs("garbage") == []

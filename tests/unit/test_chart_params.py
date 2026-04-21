"""Regression: chart param parser must survive LLM-generated malformed shapes."""
from __future__ import annotations

import pandas as pd

from backend.skills.visualization._config_parser import (
    apply_row_filter,
    parse_chart_params,
)


def test_filter_coerces_string_to_empty_dict():
    """Bug 2026-04-21: LLM generated ``"filter": "port=全港"`` (a string)
    which crashed the line chart skill with
    ``'str' object has no attribute 'items'``."""
    parsed = parse_chart_params({
        "config": {"filter": "port=全港"},
    })
    assert parsed["filter"] == {}


def test_apply_row_filter_ignores_string_input():
    """Defense in depth — skills may bypass parse_chart_params."""
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

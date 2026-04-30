"""Step 5 — fix PptxGenJS bridge invariants from the Claude SOP.

These constraints came from production debugging by an external Claude
session (see spec/refactor_report_outline.md §3 SOP recap):

  - Colors must be 6-digit hex without a leading ``#`` — pptxgenjs 4.x
    rejects ``#RRGGBB`` and produces a corrupted .pptx file.
  - In pptxgenjs 4.x the chart title parameter is ``title``, not
    ``chartTitle`` — the latter is silently ignored and renders as
    "Chart Title" in PowerPoint.
  - Shadows must use the ``opacity`` field; raw 8-digit hex (RGBA) in
    shadow color strings corrupts the file.

Each test stays small and self-contained so adding a new chart type in
Sprint 3 trips on these immediately if it regresses any constraint.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

import pytest

from backend.tools.report._pptxgen_builder import echarts_to_pptxgen

pytestmark = pytest.mark.contract


_HEX_WITH_HASH = re.compile(r"#[0-9A-Fa-f]{3,8}")
_BARE_8HEX = re.compile(r"^[0-9A-Fa-f]{8}$")
_BARE_6HEX = re.compile(r"^[0-9A-Fa-f]{6}$")


def _walk_strings(obj: Any) -> Iterable[tuple[str, str]]:
    """Yield (path, str_value) pairs for every string in a nested
    dict/list structure. Path is dotted for diagnostics."""
    def _go(node: Any, path: str):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from _go(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from _go(v, f"{path}[{i}]")
        elif isinstance(node, str):
            yield path, node
    yield from _go(obj, "")


def _walk_keys(obj: Any) -> Iterable[str]:
    """Yield every dict key seen anywhere in a nested structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


# ---------------------------------------------------------------------------
# Sample inputs — kept minimal so tests run fast
# ---------------------------------------------------------------------------

def _bar_option() -> dict:
    return {
        "title": {"text": "Sample"},
        "xAxis": {"type": "category", "data": ["A", "B", "C"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [1, 2, 3]}],
    }


def _line_option() -> dict:
    return {
        "title": {"text": "Sample"},
        "xAxis": {"type": "category", "data": ["Q1", "Q2", "Q3"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "S1", "data": [10, 20, 30]}],
    }


def _multi_series_bar() -> dict:
    return {
        "title": {"text": "Multi"},
        "xAxis": {"type": "category", "data": ["A", "B"]},
        "yAxis": {"type": "value"},
        "series": [
            {"type": "bar", "name": "S1", "data": [1, 2]},
            {"type": "bar", "name": "S2", "data": [3, 4]},
        ],
    }


def _pie_option() -> dict:
    """Phase 2.3: PIE — data is [{name, value}, ...]."""
    return {
        "title": {"text": "PieChart"},
        "series": [{
            "type": "pie", "name": "占比",
            "data": [
                {"name": "A", "value": 40},
                {"name": "B", "value": 35},
                {"name": "C", "value": 25},
            ],
        }],
    }


def _doughnut_option() -> dict:
    return {
        "title": {"text": "Doughnut"},
        "series": [{
            "type": "doughnut",
            "data": [
                {"name": "正常", "value": 80},
                {"name": "故障", "value": 15},
                {"name": "停用", "value": 5},
            ],
        }],
    }


def _horizontal_bar_option() -> dict:
    return {
        "title": {"text": "TOP3"},
        "yAxis": {"type": "category", "data": ["A", "B", "C"]},
        "xAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [100, 80, 60]}],
    }


def _combo_option() -> dict:
    """BAR + LINE on shared categories."""
    return {
        "title": {"text": "Combo"},
        "xAxis": {"type": "category", "data": ["Q1", "Q2", "Q3"]},
        "yAxis": {"type": "value"},
        "series": [
            {"type": "bar", "name": "金额", "data": [100, 200, 150]},
            {"type": "line", "name": "增长率", "data": [0.1, 0.15, 0.12]},
        ],
    }


# ---------------------------------------------------------------------------
# Constraint 1 — no leading '#' in any color string
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("option_factory", [
    _bar_option, _line_option, _multi_series_bar,
    _pie_option, _doughnut_option, _horizontal_bar_option, _combo_option,
])
def test_no_hash_prefix_in_colors(option_factory):
    spec = echarts_to_pptxgen(option_factory())
    assert spec is not None, "echarts_to_pptxgen returned None for valid input"

    bad = [
        (path, val)
        for path, val in _walk_strings(spec)
        if _HEX_WITH_HASH.search(val)
    ]
    assert not bad, (
        "PptxGenJS rejects '#RRGGBB' colors (file corruption); "
        f"violations: {bad[:5]}"
    )


# ---------------------------------------------------------------------------
# Constraint 2 — no 'chartTitle' key (renamed to 'title' in 4.x)
# ---------------------------------------------------------------------------

def test_no_chart_title_key():
    spec = echarts_to_pptxgen(_bar_option())
    assert spec is not None
    keys = list(_walk_keys(spec))
    assert "chartTitle" not in keys, (
        "pptxgenjs 4.x renamed chartTitle → title; chartTitle is silently "
        "ignored and renders 'Chart Title' placeholder."
    )


# ---------------------------------------------------------------------------
# Constraint 3 — no bare 8-digit hex (RGBA) in any color string
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("option_factory", [
    _bar_option, _line_option, _multi_series_bar,
    _pie_option, _doughnut_option, _horizontal_bar_option, _combo_option,
])
def test_no_8_digit_hex_rgba(option_factory):
    spec = echarts_to_pptxgen(option_factory())
    assert spec is not None
    bad = [
        (path, val)
        for path, val in _walk_strings(spec)
        if _BARE_8HEX.fullmatch(val)
    ]
    assert not bad, (
        "8-digit hex (RGBA) in pptxgenjs colors corrupts the .pptx; "
        f"use the ``opacity`` field instead. Violations: {bad[:5]}"
    )


# ---------------------------------------------------------------------------
# Constraint 4 — every color string is exactly 6 hex digits
# ---------------------------------------------------------------------------

def _looks_like_color_path(path: str) -> bool:
    """Match keys/paths that semantically refer to colors."""
    p = path.lower()
    return any(token in p for token in (
        "color", "fill", "chartcolors", "fontcolor",
    ))


@pytest.mark.parametrize("option_factory", [
    _bar_option, _line_option, _multi_series_bar,
    _pie_option, _doughnut_option, _horizontal_bar_option, _combo_option,
])
def test_color_strings_are_6_digit_hex(option_factory):
    spec = echarts_to_pptxgen(option_factory())
    assert spec is not None
    bad = []
    for path, val in _walk_strings(spec):
        if not _looks_like_color_path(path):
            continue
        # Skip non-hex values like 'none', 'b' (legend pos)
        if not all(c in "0123456789abcdefABCDEF" for c in val):
            continue
        if not _BARE_6HEX.fullmatch(val):
            bad.append((path, val))
    assert not bad, (
        f"Color strings must be exactly 6 hex digits; violations: {bad[:5]}"
    )


# ---------------------------------------------------------------------------
# Constraint 5 — sanity: BAR / LINE round-trip
# ---------------------------------------------------------------------------

def test_bar_option_returns_bar_type():
    spec = echarts_to_pptxgen(_bar_option())
    assert spec is not None
    assert spec["type"] == "BAR"


def test_line_option_returns_line_type():
    spec = echarts_to_pptxgen(_line_option())
    assert spec is not None
    assert spec["type"] == "LINE"


def test_unknown_chart_type_returns_none():
    """Falls back gracefully — caller renders as table."""
    scatter_option = {
        "title": {"text": "Scatter"},
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [{"type": "scatter", "data": [[1, 2], [3, 4]]}],
    }
    assert echarts_to_pptxgen(scatter_option) is None


# ---------------------------------------------------------------------------
# Phase 2.3 — new chart types
# ---------------------------------------------------------------------------

def test_pie_returns_pie_type_with_name_value_data():
    spec = echarts_to_pptxgen(_pie_option())
    assert spec is not None
    assert spec["type"] == "PIE"
    # PIE data is wrapped in pptxgenjs single-series form
    assert len(spec["data"]) == 1
    assert spec["data"][0]["labels"] == ["A", "B", "C"]
    assert spec["data"][0]["values"] == [40.0, 35.0, 25.0]
    assert spec["options"]["showPercent"] is True


def test_doughnut_returns_doughnut_with_hole():
    spec = echarts_to_pptxgen(_doughnut_option())
    assert spec is not None
    assert spec["type"] == "DOUGHNUT"
    # Hole size is required for doughnut to be visually distinct from pie
    assert "holeSize" in spec["options"]
    assert 0 < spec["options"]["holeSize"] < 100


def test_horizontal_bar_uses_bar_dir_bar():
    spec = echarts_to_pptxgen(_horizontal_bar_option())
    assert spec is not None
    assert spec["type"] == "BAR"
    assert spec["horizontal"] is True
    assert spec["options"]["barDir"] == "bar"


def test_combo_returns_multi_type_data_with_secondary_axis():
    spec = echarts_to_pptxgen(_combo_option())
    assert spec is not None
    assert spec["type"] == "COMBO"
    # data is a list of {type, data, options} entries
    assert isinstance(spec["data"], list)
    assert {entry["type"] for entry in spec["data"]} == {"BAR", "LINE"}
    line_entry = next(e for e in spec["data"] if e["type"] == "LINE")
    assert line_entry["options"].get("secondaryValAxis") is True


def test_combo_with_only_bar_falls_back_to_pure_bar():
    """COMBO requires BOTH BAR and LINE; bar-only shouldn't trigger combo."""
    pure_bar = {
        "xAxis": {"type": "category", "data": ["A"]},
        "yAxis": {"type": "value"},
        "series": [
            {"type": "bar", "name": "S1", "data": [1]},
            {"type": "bar", "name": "S2", "data": [2]},
        ],
    }
    spec = echarts_to_pptxgen(pure_bar)
    assert spec is not None
    assert spec["type"] == "BAR"


def test_pie_with_zero_total_returns_none():
    """Empty / zero-sum pie data should fall back to table."""
    bad = {
        "series": [{"type": "pie", "data": [{"name": "X", "value": 0}]}],
    }
    assert echarts_to_pptxgen(bad) is None

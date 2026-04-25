"""Shared chart-parameter normaliser.

The JSON templates describe rich chart intents in ``params.config`` — e.g.
``{"chart_type": "grouped_bar", "series": [...], "show_completion_rate_label": true}``.
Before batch 3 the chart skills read only flat fields (``title``,
``category_column``, ``value_columns``) and discarded ``config`` entirely,
so templated ``grouped_bar`` / ``dual_y_line`` / ``filter`` / ``horizontal``
requests silently fell back to default bar/line rendering — which is how
the null-filled bar chart in the 20260420_170234 report appeared.

This parser is the single place every chart skill reads its config from,
with graceful fallbacks to the legacy flat keys.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd


logger = logging.getLogger(__name__)


def _normalize_axis_spec(value: Any, field: str) -> dict[str, Any] | None:
    """Normalise dual-axis spec (left_y / right_y) into a single shape.

    Accepted inputs:
      • ``dict``       — single-series axis (e.g. ``{"label": "%", "y_field": "rate"}``)
                         passed through unchanged.
      • ``list[dict]`` — multi-series sharing one axis (e.g. utilisation +
                         serviceable rate both on the left axis). Wrapped as
                         ``{"label": joined_labels, "series": list}`` so
                         downstream renderers can iterate ``spec["series"]``.
      • ``None``       — returns None.
      • anything else  — log + drop (returns None). Caller should treat None
                         as "no axis spec; fall back to default".
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
        labels = [x.get("label", "") for x in value if x.get("label")]
        return {
            "label": " / ".join(labels) if labels else None,
            "series": value,
        }
    logger.warning(
        "chart param %r expected dict or list[dict], got %s (%r) — dropping (axis will fall back to default)",
        field, type(value).__name__, value,
    )
    return None


def _coerce_mapping(value: Any, field: str) -> dict[str, Any]:
    """Best-effort coerce an LLM-generated value into a dict.

    The planning LLM occasionally emits string scalars where the template
    expects ``dict`` — e.g. ``"filter": "port=全港"`` instead of
    ``{"port": "全港"}``. Crashing the skill here is worse than degrading
    to "no filter"; log and return an empty mapping.
    """
    if isinstance(value, dict):
        return value
    if value in (None, "", 0, False):
        return {}
    logger.warning(
        "chart param %r expected dict, got %s (%r) — dropping",
        field, type(value).__name__, value,
    )
    return {}


# Generic/placeholder chart titles that the planning LLM sometimes emits.
# When the resolved title is one of these, fall through to the task name so
# the chart gets a more descriptive heading derived from its task definition.
_GENERIC_TITLES: frozenset[str] = frozenset([
    "趋势图", "折线图", "柱状图", "饼图", "图表", "瀑布图",
    "分析图", "对比图", "图", "chart", "trend",
])

# Leading action verbs and trailing chart-type suffixes to strip when
# converting a task name (e.g. "生成全港吞吐量月度趋势折线图") into a
# concise chart title (→ "全港吞吐量月度趋势").
_TASK_NAME_PREFIXES = ("生成", "绘制", "制作", "创建", "展示", "画", "输出")
_TASK_NAME_SUFFIXES = ("折线图", "柱状图", "饼图", "瀑布图", "趋势图", "图表", "图")


def _clean_task_name_as_title(task_name: str) -> str:
    """Strip action verbs and chart-type words from a task name for use as chart title.

    Examples::

        "生成全港吞吐量月度趋势折线图" → "全港吞吐量月度趋势"
        "绘制港区吞吐量对比柱状图"    → "港区吞吐量对比"
        "分析客户贡献率"               → "分析客户贡献率"  (no match → unchanged)
    """
    name = task_name.strip()
    for prefix in _TASK_NAME_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    for suffix in _TASK_NAME_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.strip() or task_name.strip()


def parse_chart_params(params: dict[str, Any], task_name: str = "") -> dict[str, Any]:
    """Normalise template-style params into a single dict.

    Returns keys:
        title, chart_subtype, x_field, y_fields, series_by,
        left_y, right_y, filter, sort, orientation, series,
        show_completion_rate_label, data_refs, source
    """
    cfg = params.get("config") or {}

    # Title resolution (in priority order):
    #   1. config.title  — explicit per-chart override in template
    #   2. params.title  — flat legacy field from planning LLM
    #   3. task_name     — cleaned version of the task definition name
    #
    # Special case: if the resolved title is a known generic placeholder
    # (e.g. "趋势图", "图表") skip it and fall through to task_name,
    # which yields a much more descriptive heading.
    _explicit = cfg.get("title") or params.get("title") or ""
    if _explicit and _explicit.strip() not in _GENERIC_TITLES:
        title = _explicit.strip()
    elif task_name:
        title = _clean_task_name_as_title(task_name)
    else:
        title = _explicit.strip() or None

    # Fields: config.* wins, fall back to legacy flat keys
    x_field = (
        cfg.get("x_field")
        or cfg.get("category_field")
        or params.get("category_column")
        or params.get("time_column")
    )
    y_fields = (
        cfg.get("y_fields")
        or cfg.get("value_field") and [cfg["value_field"]]
        or params.get("value_columns")
        or []
    )
    if isinstance(y_fields, str):
        y_fields = [y_fields]

    # left_y / right_y: normalise into {label, series: [...]} form.
    left_y = _normalize_axis_spec(cfg.get("left_y"), "config.left_y")
    right_y = _normalize_axis_spec(cfg.get("right_y"), "config.right_y")

    # `series` must be a list of descriptors; tolerate a single-dict shape.
    series = cfg.get("series") or []
    if isinstance(series, dict):
        series = [series]
    elif not isinstance(series, list):
        logger.warning(
            "chart param config.series expected list, got %s — dropping",
            type(series).__name__,
        )
        series = []

    return {
        "title": title,
        "chart_subtype": cfg.get("chart_type"),           # e.g. "grouped_bar", "dual_y_line"
        "x_field": x_field,
        "y_fields": y_fields,
        "series_by": cfg.get("series_by"),                # field to split series by
        "left_y": left_y,                                 # dual_y_line: left-axis spec
        "right_y": right_y,                               # dual_y_line: right-axis spec
        "filter": _coerce_mapping(cfg.get("filter"), "config.filter"),
        "sort": cfg.get("sort"),                          # "asc" / "desc" / None
        "orientation": cfg.get("orientation", "vertical"),
        "series": series,                                 # grouped_bar: series descriptors
        "show_completion_rate_label": cfg.get("show_completion_rate_label", False),
        "data_refs": params.get("data_refs") or [],
        "source": cfg.get("source"),
    }


def apply_row_filter(df: pd.DataFrame, filter_dict: Any) -> pd.DataFrame:
    """Filter a DataFrame by equality on the given columns.

    Only applies filters whose column exists; unknown columns are ignored
    (templates sometimes reference fields that the underlying API didn't
    return — falling back to the unfiltered frame beats crashing).

    Defense in depth: ``filter_dict`` is also validated here because the
    skill may be called directly with an LLM-generated params blob that
    bypassed ``parse_chart_params``.
    """
    if not isinstance(filter_dict, dict) or not filter_dict:
        return df
    for k, v in filter_dict.items():
        if k in df.columns:
            df = df[df[k] == v]
    return df


def sort_df(df: pd.DataFrame, sort: str | None, by_col: str | None) -> pd.DataFrame:
    """Sort a DataFrame by a numeric column if ``sort`` is ``asc``/``desc``."""
    if not sort or sort not in ("asc", "desc") or not by_col or by_col not in df.columns:
        return df
    try:
        return df.sort_values(by_col, ascending=(sort == "asc"), kind="stable")
    except Exception:
        return df


def has_valid_series_data(series: list[dict[str, Any]]) -> bool:
    """True if any series has at least one non-null, non-zero numeric value.

    Used to gate chart output: a chart whose every series is entirely null
    is worse than no chart at all (the 20260420_170234 bar chart had this).
    """
    for s in series or []:
        data = s.get("data", [])
        for v in data:
            if v is None:
                continue
            if isinstance(v, dict):
                # echarts richer value item — treat as valid if any numeric present
                if "value" in v and v["value"] not in (None, 0):
                    return True
                continue
            if isinstance(v, (int, float)) and v != 0:
                return True
    return False


def get_df_from_context(
    source: str | None,
    context: dict[str, Any],
    data_refs: list[str] | None = None,
    fallback_context_refs: list[str] | None = None,
) -> pd.DataFrame | None:
    """Resolve a DataFrame from a source ref, with cascading fallbacks.

    Resolution order:
      1. ``source`` (when the config names an explicit task_id)
      2. each ``data_refs`` entry in order
      3. each ``fallback_context_refs`` entry in order
    Returns the first non-empty DataFrame, or None.
    """
    candidates: list[str] = []
    if source:
        candidates.append(source)
    candidates.extend(data_refs or [])
    candidates.extend(fallback_context_refs or [])

    for ref in candidates:
        if ref not in context:
            continue
        ctx_out = context[ref]
        data = ctx_out.data if hasattr(ctx_out, "data") else ctx_out
        if isinstance(data, pd.DataFrame) and not data.empty:
            return data
    return None


def format_label_as_percentage(actual: float, target: float) -> str:
    """Render ``actual/target`` as a percentage string for bar labels."""
    if target in (None, 0) or actual is None:
        return "-"
    try:
        return f"{actual / target * 100:.1f}%"
    except Exception:
        return "-"

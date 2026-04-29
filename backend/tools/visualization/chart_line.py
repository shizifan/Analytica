"""Line Chart Skill — generates ECharts line chart option JSON."""
from __future__ import annotations

from typing import Any

import pandas as pd

from backend.tools._field_labels import col_label
from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tools.visualization._config_parser import (
    apply_row_filter,
    get_df_from_context,
    has_valid_series_data,
    parse_chart_params,
)
from backend.tools.visualization._llm_mapper import decide_chart_mapping

THEME_PRIMARY = "#1E3A5F"
THEME_ACCENT = "#F0A500"
SERIES_COLORS = [THEME_PRIMARY, THEME_ACCENT, "#E85454", "#4CAF50", "#9C27B0", "#FF5722"]


def _expand_axis_subspecs(axis_spec: Any) -> list[dict[str, Any]]:
    """Return a list of single-series sub-specs from an axis spec.

    Handles both shapes produced by :func:`_normalize_axis_spec`:
      • single-series dict (e.g. ``{"source": "T003", "y_field": "qty"}``)
        → ``[axis_spec]``
      • multi-series wrapper (``{"label": ..., "series": [{...}, ...]}``)
        → each sub-spec, with the axis-level label inherited as fallback
    """
    if not isinstance(axis_spec, dict):
        return []
    inner = axis_spec.get("series")
    if isinstance(inner, list) and inner:
        parent_label = axis_spec.get("label", "")
        out: list[dict[str, Any]] = []
        for sub in inner:
            if not isinstance(sub, dict):
                continue
            merged = {"label": parent_label, **sub}
            out.append(merged)
        return out
    return [axis_spec]


def _build_series_for_axis(
    df: pd.DataFrame,
    axis_spec: dict[str, Any],
    x_values: list[str],
    x_field: str,
    y_axis_idx: int,
    color_offset: int = 0,
) -> list[dict[str, Any]]:
    """Build echarts line series on a specific yAxisIndex from a dual-axis spec.

    axis_spec example:
        {"source": "T003", "y_field": "qty", "series_by": "year", "label": "吞吐量"}

    ``x_field`` is the column in *this* frame to key against; it may differ
    between the left and right axes (different APIs may return different
    time-axis column names).
    """
    y_field = axis_spec.get("y_field")
    series_by = axis_spec.get("series_by")
    label = axis_spec.get("label") or col_label(y_field or "value")
    if not y_field or y_field not in df.columns or x_field not in df.columns:
        return []

    # Cast the per-frame x column to string so lookups against x_values
    # (which is built from the union of string-cast values) match reliably.
    df = df.copy()
    df[x_field] = df[x_field].astype(str)

    series: list[dict[str, Any]] = []

    if series_by and series_by in df.columns:
        # One line per distinct value of series_by (e.g. year 2025 vs 2026)
        for i, (group_val, sub_df) in enumerate(df.groupby(series_by, sort=True)):
            sub_df = sub_df.set_index(x_field)
            data = [
                round(float(sub_df[y_field].get(x)), 2)
                if x in sub_df.index and pd.notna(sub_df[y_field].get(x))
                else None
                for x in x_values
            ]
            color = SERIES_COLORS[(color_offset + i) % len(SERIES_COLORS)]
            series.append({
                "name": f"{group_val} {label}",
                "type": "line",
                "yAxisIndex": y_axis_idx,
                "data": data,
                "smooth": True,
                "lineStyle": {"color": color},
                "itemStyle": {"color": color},
            })
    else:
        # Single series on this axis
        indexed = df.set_index(x_field)
        data = [
            round(float(indexed[y_field].get(x)), 2)
            if x in indexed.index and pd.notna(indexed[y_field].get(x))
            else None
            for x in x_values
        ]
        color = SERIES_COLORS[color_offset % len(SERIES_COLORS)]
        series.append({
            "name": label,
            "type": "line",
            "yAxisIndex": y_axis_idx,
            "data": data,
            "smooth": True,
            "lineStyle": {"color": color},
            "itemStyle": {"color": color},
        })

    return series


@register_tool("tool_chart_line", ToolCategory.VISUALIZATION, "折线图生成（ECharts option JSON）",
                input_spec="data_ref/data_refs + config{chart_type,left_y,right_y,...}",
                output_spec="ECharts option JSON")
class LineChartTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        params = inp.params
        intent = params.get("intent") or params.get("_task_name", "")
        task_id = params.get("__task_id__", "")

        # dual_y_line requires explicit left/right source config — keep existing path
        parsed = parse_chart_params(params, intent)
        if parsed["chart_subtype"] == "dual_y_line" and parsed["left_y"] and parsed["right_y"]:
            return self._render_dual_y(parsed, context)

        # Get DataFrame from context (multiple fallback strategies)
        df = get_df_from_context(
            source=parsed["source"],
            context=context,
            data_refs=parsed["data_refs"],
            fallback_context_refs=inp.context_refs or [],
        )
        if df is None and params.get("data_ref"):
            data_ref = params["data_ref"]
            if isinstance(data_ref, list):
                data_ref = data_ref[0] if data_ref else None
            if data_ref and data_ref in context:
                d = context[data_ref].data
                if isinstance(d, pd.DataFrame) and not d.empty:
                    df = d
        if df is None:
            for ctx_out in context.values():
                d = ctx_out.data if hasattr(ctx_out, "data") else ctx_out
                if isinstance(d, pd.DataFrame) and not d.empty:
                    df = d
                    break
        if df is None:
            return self._fail("无法获取有效的 DataFrame 数据")

        df = apply_row_filter(df, parsed["filter"])
        if df.empty:
            return ToolOutput(
                tool_id=self.tool_id, status="skipped", output_type="chart",
                error_message=f"filter 后无数据: {parsed['filter']}",
                metadata={"skip_reason": "EMPTY_AFTER_FILTER"},
            )

        # LLM decides axis/series mapping based on actual DataFrame columns.
        # Passes context so decide_chart_mapping can reuse display_hint from
        # upstream api_fetch and skip the LLM call when the hint is valid.
        mapping = await decide_chart_mapping(
            df, intent, "line",
            span_emit=inp.span_emit,
            task_id=task_id,
            context=context,
        )
        return self._render_with_mapping(df, mapping)

    # ── LLM-mapped single-axis line ───────────────────────────
    def _render_with_mapping(self, df: pd.DataFrame, mapping: dict[str, Any]) -> ToolOutput:
        x_field = mapping["x_field"]
        y_fields = mapping["y_fields"]
        series_by = mapping.get("series_by")
        title = mapping.get("title") or "趋势图"
        y_axis_label = mapping.get("y_axis_label", "")

        series: list[dict[str, Any]] = []

        if series_by and series_by in df.columns:
            y_field = y_fields[0]
            x_data = sorted(df[x_field].astype(str).unique().tolist())
            for i, (group_val, sub_df) in enumerate(df.groupby(series_by, sort=True)):
                sub_df = sub_df.copy()
                sub_df[x_field] = sub_df[x_field].astype(str)
                indexed = sub_df.set_index(x_field)
                data = [
                    round(float(indexed[y_field].get(x)), 2)
                    if x in indexed.index and pd.notna(indexed[y_field].get(x))
                    else None
                    for x in x_data
                ]
                color = SERIES_COLORS[i % len(SERIES_COLORS)]
                series.append({
                    "name": str(group_val),
                    "type": "line",
                    "data": data,
                    "smooth": True,
                    "lineStyle": {"color": color},
                    "itemStyle": {"color": color},
                })
        else:
            x_data = [str(v) for v in df[x_field].tolist()]
            for i, col in enumerate(y for y in y_fields if y in df.columns):
                color = SERIES_COLORS[i % len(SERIES_COLORS)]
                series.append({
                    "name": col_label(col),
                    "type": "line",
                    "data": [round(float(v), 2) if pd.notna(v) else None for v in df[col]],
                    "smooth": True,
                    "lineStyle": {"color": color},
                    "itemStyle": {"color": color},
                })

        if not has_valid_series_data(series):
            return ToolOutput(
                tool_id=self.tool_id, status="skipped", output_type="chart",
                error_message="所有数值均为 null",
                metadata={"skip_reason": "ALL_NULL"},
            )

        option = {
            "title": {"text": title, "left": "center", "textStyle": {"color": THEME_PRIMARY}},
            "tooltip": {"trigger": "axis"},
            "legend": {"data": [s["name"] for s in series], "bottom": 0},
            "xAxis": {"type": "category", "data": x_data},
            "yAxis": {"type": "value", "name": y_axis_label},
            "series": series,
            "color": SERIES_COLORS[:len(series)],
        }
        return ToolOutput(
            tool_id=self.tool_id, status="success", output_type="chart",
            data=option,
            metadata={"chart_type": "line", "chart_subtype": "single_y",
                      "series_count": len(series), "rows": len(df)},
        )

    # ── Dual Y-axis line ──────────────────────────────────────
    def _render_dual_y(
        self,
        parsed: dict[str, Any],
        context: dict[str, Any],
    ) -> ToolOutput:
        left_subs = _expand_axis_subspecs(parsed.get("left_y"))
        right_subs = _expand_axis_subspecs(parsed.get("right_y"))
        x_field = parsed["x_field"]

        # Resolve each sub-spec to (sub, df, axis_idx). Drop sub-specs whose
        # source can't be found / is empty; carry on with the rest rather
        # than failing the whole chart.
        resolved: list[tuple[dict[str, Any], pd.DataFrame, int]] = []
        unresolved_sources: list[str] = []
        for axis_idx, subs in ((0, left_subs), (1, right_subs)):
            for sub in subs:
                src = sub.get("source")
                if not src:
                    continue
                ctx_out = context.get(src)
                d = getattr(ctx_out, "data", None)
                if isinstance(d, pd.DataFrame) and not d.empty:
                    resolved.append((sub, d, axis_idx))
                else:
                    unresolved_sources.append(src)

        if not resolved:
            return self._fail(
                f"dual_y_line: 无法解析任何 axis source "
                f"(left={[s.get('source') for s in left_subs]}, "
                f"right={[s.get('source') for s in right_subs]})"
            )

        # Build union of x categories across all resolved frames (string-cast
        # for consistency). Each frame may use a different x column name.
        x_set: set[str] = set()
        per_sub_x: list[str] = []
        for sub, df, _ in resolved:
            sub_x = sub.get("x_field") or x_field
            if not sub_x or sub_x not in df.columns:
                sub_x = self._auto_detect_time(df) or ""
            per_sub_x.append(sub_x)
            if sub_x and sub_x in df.columns:
                x_set |= set(df[sub_x].astype(str))
        x_values = sorted(x_set)

        if not x_values:
            return self._fail(
                f"dual_y_line: 无法确定时间轴。columns sampled: "
                f"{[list(df.columns)[:6] for _, df, _ in resolved]}"
            )

        # Build all series, accumulating colour offset across both axes.
        series: list[dict[str, Any]] = []
        color_idx = 0
        for (sub, df, axis_idx), sub_x in zip(resolved, per_sub_x):
            if not sub_x or sub_x not in df.columns:
                continue
            new_series = _build_series_for_axis(df, sub, x_values, sub_x, axis_idx, color_idx)
            series.extend(new_series)
            color_idx += len(new_series)

        if not has_valid_series_data(series):
            return ToolOutput(
                tool_id=self.tool_id, status="skipped", output_type="chart",
                error_message="dual_y_line: 所有序列数据均为空",
                metadata={"skip_reason": "ALL_NULL", "chart_subtype": "dual_y_line"},
            )

        # Axis labels: prefer wrapper-level label, else first sub-spec's label.
        def _axis_label(spec: Any, subs: list[dict[str, Any]]) -> str:
            if isinstance(spec, dict) and spec.get("label"):
                return spec["label"]
            return subs[0].get("label", "") if subs else ""

        option = {
            "title": {"text": parsed["title"] or "双轴趋势", "left": "center",
                      "textStyle": {"color": THEME_PRIMARY}},
            "tooltip": {"trigger": "axis"},
            "legend": {"data": [s["name"] for s in series], "bottom": 0},
            "xAxis": {"type": "category", "data": x_values},
            "yAxis": [
                {"type": "value", "name": _axis_label(parsed.get("left_y"), left_subs)},
                {"type": "value", "name": _axis_label(parsed.get("right_y"), right_subs)},
            ],
            "series": series,
        }

        meta: dict[str, Any] = {
            "chart_type": "line",
            "chart_subtype": "dual_y_line",
            "series_count": len(series),
            "left_subspecs": len(left_subs),
            "right_subspecs": len(right_subs),
        }
        if unresolved_sources:
            meta["unresolved_sources"] = unresolved_sources
            meta["degraded"] = True

        return ToolOutput(
            tool_id=self.tool_id, status="success", output_type="chart",
            data=option, metadata=meta,
        )

    @staticmethod
    def _find_common_time_col(
        df_left: pd.DataFrame,
        df_right: pd.DataFrame,
    ) -> str | None:
        """Return a non-numeric column present in both frames whose name
        suggests a time axis, preferring the first match in priority order."""
        _PREFERENCE = ("dateMonth", "monthStr", "monthId", "month",
                       "date", "dateStr", "period", "quarter", "year")
        common = set(df_left.columns) & set(df_right.columns)
        for key in _PREFERENCE:
            if key in common:
                return key
        for c in common:
            if any(kw in c.lower() for kw in ("date", "month", "year", "time", "period")):
                # Ensure it's not purely numeric in either frame
                if (not pd.api.types.is_numeric_dtype(df_left[c])
                        and not pd.api.types.is_numeric_dtype(df_right[c])):
                    return c
        return None

    @staticmethod
    def _auto_detect_time(df: pd.DataFrame) -> str | None:
        _DATE_KEYWORDS = ("date", "month", "year", "time", "day", "period", "quarter")
        date_cols = [
            c for c in df.columns
            if any(kw in c.lower() for kw in _DATE_KEYWORDS)
            and not pd.api.types.is_numeric_dtype(df[c])
        ]
        return date_cols[0] if date_cols else next(
            (col for col in df.columns if not pd.api.types.is_numeric_dtype(df[col])), None
        )

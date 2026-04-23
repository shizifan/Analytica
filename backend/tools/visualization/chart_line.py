"""Line Chart Skill — generates ECharts line chart option JSON."""
from __future__ import annotations

from typing import Any

import pandas as pd

from backend.tools._i18n import col_label
from backend.tools.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.tools.registry import register_skill
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


@register_skill("skill_chart_line", SkillCategory.VISUALIZATION, "折线图生成（ECharts option JSON）",
                input_spec="data_ref/data_refs + config{chart_type,left_y,right_y,...}",
                output_spec="ECharts option JSON")
class LineChartSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
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
            return SkillOutput(
                skill_id=self.skill_id, status="skipped", output_type="chart",
                error_message=f"filter 后无数据: {parsed['filter']}",
                metadata={"skip_reason": "EMPTY_AFTER_FILTER"},
            )

        # LLM decides axis/series mapping based on actual DataFrame columns
        mapping = await decide_chart_mapping(
            df, intent, "line",
            span_emit=inp.span_emit,
            task_id=task_id,
        )
        return self._render_with_mapping(df, mapping)

    # ── LLM-mapped single-axis line ───────────────────────────
    def _render_with_mapping(self, df: pd.DataFrame, mapping: dict[str, Any]) -> SkillOutput:
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
            return SkillOutput(
                skill_id=self.skill_id, status="skipped", output_type="chart",
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
        return SkillOutput(
            skill_id=self.skill_id, status="success", output_type="chart",
            data=option,
            metadata={"chart_type": "line", "chart_subtype": "single_y",
                      "series_count": len(series), "rows": len(df)},
        )

    # ── Dual Y-axis line ──────────────────────────────────────
    def _render_dual_y(
        self,
        parsed: dict[str, Any],
        context: dict[str, Any],
    ) -> SkillOutput:
        left_spec = parsed["left_y"]
        right_spec = parsed["right_y"]
        x_field = parsed["x_field"]

        df_left = None
        df_right = None
        if left_spec.get("source") and left_spec["source"] in context:
            d = context[left_spec["source"]].data
            if isinstance(d, pd.DataFrame) and not d.empty:
                df_left = d
        if right_spec.get("source") and right_spec["source"] in context:
            d = context[right_spec["source"]].data
            if isinstance(d, pd.DataFrame) and not d.empty:
                df_right = d

        if df_left is None or df_right is None:
            return self._fail(
                f"dual_y_line: 无法解析 source (left={left_spec.get('source')}, "
                f"right={right_spec.get('source')})"
            )

        # Resolve per-axis x_field. Different APIs on the left/right sources
        # may return different time-axis column names (e.g. T003 uses
        # ``dateMonth`` while T004 uses ``month``). Prefer the axis-spec
        # override > top-level x_field > auto-detected date-ish column.
        left_x = (left_spec.get("x_field") or x_field) if isinstance(left_spec, dict) else x_field
        right_x = (right_spec.get("x_field") or x_field) if isinstance(right_spec, dict) else x_field
        if not left_x or left_x not in df_left.columns:
            left_x = self._auto_detect_time(df_left)
        if not right_x or right_x not in df_right.columns:
            right_x = self._auto_detect_time(df_right)
        if not left_x or not right_x:
            return self._fail(
                f"dual_y_line: 无法确定时间轴。left.columns={list(df_left.columns)[:6]}, "
                f"right.columns={list(df_right.columns)[:6]}"
            )

        # Union of x categories from both frames (string-cast for consistency)
        x_values = sorted(
            set(df_left[left_x].astype(str)) | set(df_right[right_x].astype(str))
        )

        series_left = _build_series_for_axis(df_left, left_spec, x_values, left_x, 0, 0)
        series_right = _build_series_for_axis(df_right, right_spec, x_values, right_x, 1,
                                              len(series_left))
        series = series_left + series_right

        if not has_valid_series_data(series):
            return SkillOutput(
                skill_id=self.skill_id, status="skipped", output_type="chart",
                error_message="dual_y_line: 所有序列数据均为空",
                metadata={"skip_reason": "ALL_NULL", "chart_subtype": "dual_y_line"},
            )

        option = {
            "title": {"text": parsed["title"] or "双轴趋势", "left": "center",
                      "textStyle": {"color": THEME_PRIMARY}},
            "tooltip": {"trigger": "axis"},
            "legend": {"data": [s["name"] for s in series], "bottom": 0},
            "xAxis": {"type": "category", "data": x_values},
            "yAxis": [
                {"type": "value", "name": left_spec.get("label", "")},
                {"type": "value", "name": right_spec.get("label", "")},
            ],
            "series": series,
        }

        return SkillOutput(
            skill_id=self.skill_id, status="success", output_type="chart",
            data=option,
            metadata={
                "chart_type": "line",
                "chart_subtype": "dual_y_line",
                "series_count": len(series),
            },
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

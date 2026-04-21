"""Bar Chart Skill — generates ECharts bar chart option JSON.

Batch 3 rewrite: consumes ``params.config`` so templated ``grouped_bar`` and
``horizontal`` intents actually render correctly (previously both fell back
to generic vertical single-series output with null data).
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from backend.skills._i18n import col_label
from backend.skills.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.skills.registry import register_skill
from backend.skills.visualization._config_parser import (
    apply_row_filter,
    format_label_as_percentage,
    get_df_from_context,
    has_valid_series_data,
    parse_chart_params,
    sort_df,
)

THEME_PRIMARY = "#1E3A5F"
THEME_ACCENT = "#F0A500"
SERIES_COLORS = [THEME_PRIMARY, THEME_ACCENT, "#E85454", "#4CAF50"]


def _resolve_cell(expr: str, context: dict[str, Any]) -> float | None:
    """Resolve a ``Txxx.fieldName`` expression against the execution context.

    Returns a float or None. Used by ``grouped_bar`` series specs like
    ``{"target": "T001.targetQty", "actual": "T001.finishQty"}``.
    """
    if not expr or "." not in expr:
        return None
    task_id, field = expr.split(".", 1)
    if task_id not in context:
        return None
    ctx_out = context[task_id]
    data = ctx_out.data if hasattr(ctx_out, "data") else ctx_out
    if isinstance(data, pd.DataFrame) and not data.empty and field in data.columns:
        try:
            return float(data.iloc[0][field])
        except Exception:
            return None
    if isinstance(data, dict) and field in data:
        try:
            return float(data[field])
        except Exception:
            return None
    return None


@register_skill("skill_chart_bar", SkillCategory.VISUALIZATION, "柱状图生成（ECharts option JSON）",
                input_spec="data_ref/data_refs + config{chart_type,series,filter,...}",
                output_spec="ECharts option JSON")
class BarChartSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        params = inp.params
        task_name = params.get("_task_name", "")  # set by execution.py if available
        parsed = parse_chart_params(params, task_name)
        subtype = parsed["chart_subtype"]

        # ── Subtype: grouped_bar (target vs actual) ─────────────
        # Template pattern: params.config.series = [
        #   {"label": "吨吞吐", "target": "T001.targetQty", "actual": "T001.finishQty"},
        #   {"label": "集装箱", "target": "T002.targetQty", "actual": "T002.finishQty"},
        # ]
        if subtype == "grouped_bar" and parsed["series"]:
            return self._render_grouped_bar(parsed, context)

        # ── Generic path (covers default vertical/horizontal single-source) ──
        return self._render_generic(parsed, params, inp.context_refs or [], context)

    # ── Grouped-bar (target vs actual OR multi-source comparison) ──
    def _render_grouped_bar(
        self,
        parsed: dict[str, Any],
        context: dict[str, Any],
    ) -> SkillOutput:
        """Two grouped-bar patterns are supported:

        A. **KPI target-vs-actual** (one row per label from a single task):
           series = [{"label":"吨","target":"T001.targetQty","actual":"T001.finishQty"}]
           → one pair of bars per series entry.

        B. **Multi-source by category** (two tasks sharing the same x_field):
           series = [{"label":"当月","source":"T006","y_field":"num"},
                     {"label":"年累计","source":"T007","y_field":"num"}]
           x_field = "categoryName"
           → bars grouped by category, one series per source task.

        We detect pattern B when the first series entry carries a ``source``
        key (no ``target``/``actual``).
        """
        first = parsed["series"][0] if parsed["series"] else {}
        is_pattern_b = "source" in first and "target" not in first and "actual" not in first

        if is_pattern_b:
            return self._render_multi_source_grouped(parsed, context)

        # ── Pattern A: target vs actual ──
        categories: list[str] = []
        target_vals: list[float | None] = []
        actual_vals: list[float | None] = []
        rate_labels: list[str] = []

        for item in parsed["series"]:
            label = item.get("label") or "-"
            target = _resolve_cell(item.get("target", ""), context)
            actual = _resolve_cell(item.get("actual", ""), context)
            categories.append(label)
            target_vals.append(target)
            actual_vals.append(actual)
            rate_labels.append(format_label_as_percentage(actual or 0, target or 0))

        series = [
            {"name": "目标", "type": "bar",
             "data": target_vals, "itemStyle": {"color": THEME_PRIMARY}},
            {"name": "实际", "type": "bar",
             "data": actual_vals, "itemStyle": {"color": THEME_ACCENT}},
        ]

        # Completion rate label on the "actual" bar
        if parsed["show_completion_rate_label"]:
            series[1]["label"] = {
                "show": True,
                "position": "top",
                "formatter": "{c}",  # echarts will render the data value; frontend can format
            }

        if not has_valid_series_data(series):
            return SkillOutput(
                skill_id=self.skill_id, status="skipped", output_type="chart",
                error_message="grouped_bar: 所有目标/实际值均为 null",
                metadata={"skip_reason": "ALL_NULL", "chart_subtype": "grouped_bar"},
            )

        option = {
            "title": {"text": parsed["title"] or "目标完成对比", "left": "center",
                      "textStyle": {"color": THEME_PRIMARY}},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "legend": {"data": [s["name"] for s in series], "bottom": 0},
            "xAxis": {"type": "category", "data": categories},
            "yAxis": {"type": "value"},
            "series": series,
        }

        return SkillOutput(
            skill_id=self.skill_id, status="success", output_type="chart",
            data=option,
            metadata={
                "chart_type": "bar",
                "chart_subtype": "grouped_bar",
                "series_count": 2,
                "completion_rates": rate_labels,
            },
        )

    # ── Pattern B: multi-source grouped by x_field ─────────────
    def _render_multi_source_grouped(
        self,
        parsed: dict[str, Any],
        context: dict[str, Any],
    ) -> SkillOutput:
        """Pattern B: one series per upstream task, bars grouped by x_field.

        Example template:
            x_field="categoryName", series=[
              {"label":"当月","source":"T006","y_field":"num"},
              {"label":"年累计","source":"T007","y_field":"num"}]

        All series are joined on x_field (union of categories across tasks).
        Missing values become null → excluded from the has_valid_series_data
        gate only when *every* entry is null.
        """
        x_field = parsed["x_field"]
        if not x_field:
            return self._fail("多源 grouped_bar 需要 config.x_field")

        # Collect categories (union across sources) and per-source maps
        per_series: list[dict[str, Any]] = []
        all_categories: list[str] = []
        seen: set[str] = set()

        for item in parsed["series"]:
            source = item.get("source") or ""
            y_field = item.get("y_field") or ""
            label = item.get("label") or source or y_field or "-"
            if source not in context:
                per_series.append({"label": label, "map": {}})
                continue
            df = context[source].data if hasattr(context[source], "data") else None
            if df is None or not hasattr(df, "columns") or x_field not in df.columns or y_field not in df.columns:
                per_series.append({"label": label, "map": {}})
                continue
            # Build {category: value} map
            value_map: dict[str, float] = {}
            for _, row in df.iterrows():
                try:
                    cat = str(row[x_field])
                    val = float(row[y_field])
                except Exception:
                    continue
                value_map[cat] = val
                if cat not in seen:
                    seen.add(cat)
                    all_categories.append(cat)
            per_series.append({"label": label, "map": value_map})

        if not all_categories:
            return SkillOutput(
                skill_id=self.skill_id, status="skipped", output_type="chart",
                error_message="多源 grouped_bar: 未找到共同类别",
                metadata={"skip_reason": "NO_CATEGORIES", "chart_subtype": "grouped_bar"},
            )

        series = []
        for i, s in enumerate(per_series):
            vmap = s["map"]
            data = [round(vmap[c], 2) if c in vmap else None for c in all_categories]
            series.append({
                "name": s["label"],
                "type": "bar",
                "data": data,
                "itemStyle": {"color": SERIES_COLORS[i % len(SERIES_COLORS)]},
            })

        if not has_valid_series_data(series):
            return SkillOutput(
                skill_id=self.skill_id, status="skipped", output_type="chart",
                error_message="多源 grouped_bar: 所有系列数据均为 null",
                metadata={"skip_reason": "ALL_NULL", "chart_subtype": "grouped_bar"},
            )

        option = {
            "title": {"text": parsed["title"] or "多源对比", "left": "center",
                      "textStyle": {"color": THEME_PRIMARY}},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "legend": {"data": [s["name"] for s in series], "bottom": 0},
            "xAxis": {"type": "category", "data": all_categories},
            "yAxis": {"type": "value"},
            "series": series,
        }

        return SkillOutput(
            skill_id=self.skill_id, status="success", output_type="chart",
            data=option,
            metadata={
                "chart_type": "bar",
                "chart_subtype": "grouped_bar_multi_source",
                "series_count": len(series),
                "category_count": len(all_categories),
            },
        )

    # ── Generic single-source bar ─────────────────────────────
    def _render_generic(
        self,
        parsed: dict[str, Any],
        params: dict[str, Any],
        fallback_refs: list[str],
        context: dict[str, Any],
    ) -> SkillOutput:
        # Resolve DataFrame: explicit source > data_refs > context_refs > any frame
        df = get_df_from_context(
            source=parsed["source"],
            context=context,
            data_refs=parsed["data_refs"],
            fallback_context_refs=fallback_refs,
        )
        # Legacy support for data_ref singular key
        if df is None and params.get("data_ref"):
            data_ref = params["data_ref"]
            if isinstance(data_ref, list):
                data_ref = data_ref[0] if data_ref else None
            if data_ref and data_ref in context:
                d = context[data_ref].data if hasattr(context[data_ref], "data") else None
                if isinstance(d, pd.DataFrame) and not d.empty:
                    df = d
        if df is None:
            # Deep fallback: pick first non-empty DataFrame in the context.
            for ctx_out in context.values():
                d = ctx_out.data if hasattr(ctx_out, "data") else ctx_out
                if isinstance(d, pd.DataFrame) and not d.empty:
                    df = d
                    break
        if df is None:
            return self._fail("无法获取有效的 DataFrame 数据")

        # Apply filter first (narrows rows before axis/series detection)
        df = apply_row_filter(df, parsed["filter"])
        if df.empty:
            return SkillOutput(
                skill_id=self.skill_id, status="skipped", output_type="chart",
                error_message=f"filter 后无数据: {parsed['filter']}",
                metadata={"skip_reason": "EMPTY_AFTER_FILTER"},
            )

        # Category column
        x_field = parsed["x_field"]
        if not x_field or x_field not in df.columns:
            x_field = self._auto_detect_x(df)
        if not x_field:
            return self._fail("未找到合适的分类列")

        # Value columns
        y_fields = [y for y in parsed["y_fields"] if y in df.columns]
        if not y_fields:
            y_fields = [c for c in df.columns
                        if c != x_field and pd.api.types.is_numeric_dtype(df[c])]
        if not y_fields:
            return self._fail("无有效的数值列")

        # Sort: if sort requested, sort by first y_field
        df = sort_df(df, parsed["sort"], y_fields[0])

        x_data = [str(v) for v in df[x_field].tolist()]

        series = []
        for i, col in enumerate(y_fields):
            series.append({
                "name": col_label(col),
                "type": "bar",
                "data": [round(float(v), 2) if pd.notna(v) else None for v in df[col]],
                "itemStyle": {"color": SERIES_COLORS[i % len(SERIES_COLORS)]},
            })

        if not has_valid_series_data(series):
            return SkillOutput(
                skill_id=self.skill_id, status="skipped", output_type="chart",
                error_message="所有数值均为 null",
                metadata={"skip_reason": "ALL_NULL"},
            )

        is_horizontal = parsed["orientation"] == "horizontal"
        option = {
            "title": {"text": parsed["title"] or "数据对比", "left": "center",
                      "textStyle": {"color": THEME_PRIMARY}},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "legend": {"data": [s["name"] for s in series], "bottom": 0},
        }
        if is_horizontal:
            option["xAxis"] = {"type": "value"}
            option["yAxis"] = {"type": "category", "data": x_data}
        else:
            option["xAxis"] = {"type": "category", "data": x_data}
            option["yAxis"] = {"type": "value"}
        option["series"] = series

        return SkillOutput(
            skill_id=self.skill_id, status="success", output_type="chart",
            data=option,
            metadata={
                "chart_type": "bar",
                "chart_subtype": "horizontal" if is_horizontal else "vertical",
                "series_count": len(series),
                "rows": len(df),
            },
        )

    @staticmethod
    def _auto_detect_x(df: pd.DataFrame) -> str | None:
        _DATE_KEYWORDS = ("date", "month", "year", "time", "day", "period", "quarter")
        date_cols = [
            c for c in df.columns
            if any(kw in c.lower() for kw in _DATE_KEYWORDS)
            and not pd.api.types.is_numeric_dtype(df[c])
        ]
        if date_cols:
            return date_cols[0]
        for col in df.columns:
            if not pd.api.types.is_numeric_dtype(df[col]):
                return col
        return None

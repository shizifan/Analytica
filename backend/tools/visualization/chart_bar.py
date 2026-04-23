"""Bar Chart Skill — generates ECharts bar chart option JSON."""
from __future__ import annotations

from typing import Any

import pandas as pd

from backend.tools._i18n import col_label
from backend.tools.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.tools.registry import register_skill
from backend.tools.visualization._config_parser import (
    apply_row_filter,
    format_label_as_percentage,
    get_df_from_context,
    has_valid_series_data,
    parse_chart_params,
    sort_df,
)
from backend.tools.visualization._llm_mapper import decide_chart_mapping

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
        intent = params.get("intent") or params.get("_task_name", "")
        task_id = params.get("__task_id__", "")
        parsed = parse_chart_params(params, intent)
        subtype = parsed["chart_subtype"]

        # grouped_bar requires explicit series config (target/actual or multi-source) — keep
        if subtype == "grouped_bar" and parsed["series"]:
            return self._render_grouped_bar(parsed, context)

        # Get DataFrame from context
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
                d = context[data_ref].data if hasattr(context[data_ref], "data") else None
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

        # LLM decides axis/series mapping based on actual DataFrame columns.
        # Passes context so decide_chart_mapping can reuse display_hint from
        # upstream api_fetch and skip the LLM call when the hint is valid.
        mapping = await decide_chart_mapping(
            df, intent, "bar",
            span_emit=inp.span_emit,
            task_id=task_id,
            context=context,
        )
        return self._render_with_mapping(df, mapping)

    # ── LLM-mapped single-source bar ──────────────────────────
    def _render_with_mapping(self, df: pd.DataFrame, mapping: dict[str, Any]) -> SkillOutput:
        x_field = mapping["x_field"]
        y_fields = mapping["y_fields"]
        series_by = mapping.get("series_by")
        title = mapping.get("title") or "数据对比"
        sort = mapping.get("sort")
        is_horizontal = mapping.get("orientation") == "horizontal"

        series: list[dict[str, Any]] = []

        if series_by and series_by in df.columns:
            y_field = y_fields[0]
            all_x = list(dict.fromkeys(str(v) for v in df[x_field]))
            for i, (group_val, sub_df) in enumerate(df.groupby(series_by, sort=True)):
                sub_df = sub_df.copy()
                sub_df[x_field] = sub_df[x_field].astype(str)
                indexed = sub_df.set_index(x_field)
                data = [
                    round(float(indexed[y_field].get(x)), 2)
                    if x in indexed.index and pd.notna(indexed[y_field].get(x))
                    else None
                    for x in all_x
                ]
                series.append({
                    "name": str(group_val),
                    "type": "bar",
                    "data": data,
                    "itemStyle": {"color": SERIES_COLORS[i % len(SERIES_COLORS)]},
                })
            x_data = all_x
        else:
            y_field = y_fields[0] if y_fields else None
            if y_field and sort:
                df = sort_df(df, sort, y_field)
            x_data = [str(v) for v in df[x_field].tolist()]
            for i, col in enumerate(y for y in y_fields if y in df.columns):
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

        option: dict[str, Any] = {
            "title": {"text": title, "left": "center", "textStyle": {"color": THEME_PRIMARY}},
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
            metadata={"chart_type": "bar",
                      "chart_subtype": "horizontal" if is_horizontal else "vertical",
                      "series_count": len(series), "rows": len(df)},
        )

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


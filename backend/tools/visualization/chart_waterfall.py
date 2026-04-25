"""Waterfall Chart Skill — generates ECharts waterfall chart for attribution visualization."""
from __future__ import annotations

from typing import Any

import pandas as pd

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tools.visualization._config_parser import (
    apply_row_filter,
    get_df_from_context,
    has_valid_series_data,
    parse_chart_params,
)
from backend.tools.visualization._llm_mapper import decide_chart_mapping

COLOR_BASE = "#1E3A5F"      # deep blue for base/total
COLOR_POSITIVE = "#F0A500"  # amber for positive
COLOR_NEGATIVE = "#E85454"  # red for negative


def _derive_waterfall_from_df(
    df: pd.DataFrame,
    category_field: str,
    value_field: str,
    filter_dict: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert a filtered DataFrame into the waterfall_data list shape.

    Produces: [baseline=0, item_1, item_2, ..., net_total]

    If the filter removes all rows (template filter fields don't match what
    the API actually returned), retry once without the filter so the chart
    can still render — better than the hard fail we had in batch 2.
    """
    if category_field not in df.columns or value_field not in df.columns:
        return []

    filtered = apply_row_filter(df, filter_dict) if filter_dict else df
    if filtered.empty and filter_dict:
        # Fall back to the unfiltered frame with a diagnostic prefix row
        filtered = df
        fallback_note = True
    else:
        fallback_note = False

    if filtered.empty:
        return []

    rows: list[dict[str, Any]] = [{"name": "起始", "value": 0}]
    total = 0.0
    for _, r in filtered.iterrows():
        try:
            v = float(r[value_field])
        except Exception:
            continue
        rows.append({"name": str(r[category_field]), "value": v})
        total += v
    rows.append({"name": "合计", "value": total})
    if fallback_note:
        rows[0] = {"name": "起始(filter无匹配)", "value": 0}
    return rows


def _extract_waterfall_from_context(
    context: dict[str, Any],
    refs: list[str],
) -> list[dict[str, Any]]:
    """Look for upstream attribution output carrying ``waterfall_data``."""
    for ref in refs:
        if ref not in context:
            continue
        ctx_out = context[ref]
        data = ctx_out.data if hasattr(ctx_out, "data") else ctx_out
        if isinstance(data, dict):
            wf = data.get("waterfall_data")
            if isinstance(wf, list) and wf:
                return wf
    return []


@register_tool("tool_chart_waterfall", ToolCategory.VISUALIZATION, "瀑布图生成（归因可视化）",
                input_spec="waterfall_data OR config{category_field,value_field,filter}",
                output_spec="ECharts option JSON")
class WaterfallChartTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        params = inp.params
        intent = params.get("intent") or params.get("_task_name", "")
        task_id = params.get("__task_id__", "")
        parsed = parse_chart_params(params, intent)

        # Resolution order:
        # 1) explicit params.waterfall_data (legacy / attribution skill output)
        # 2) extract from upstream attribution's waterfall_data in context
        # 3) derive from DataFrame — LLM decides category_field / value_field
        waterfall_data = params.get("waterfall_data") or []

        if not waterfall_data:
            waterfall_data = _extract_waterfall_from_context(context, inp.context_refs or [])

        if not waterfall_data:
            df = get_df_from_context(
                source=parsed["source"],
                context=context,
                data_refs=parsed["data_refs"],
                fallback_context_refs=inp.context_refs or [],
            )
            if df is not None and not df.empty:
                mapping = await decide_chart_mapping(
                    df, intent, "waterfall",
                    span_emit=inp.span_emit,
                    task_id=task_id,
                )
                category_field = mapping.get("category_field", "")
                value_field = mapping.get("value_field", "")
                if category_field and value_field:
                    waterfall_data = _derive_waterfall_from_df(
                        df, category_field, value_field, parsed["filter"],
                    )
                    if not waterfall_data:
                        # filter may have removed everything — try without filter
                        waterfall_data = _derive_waterfall_from_df(df, category_field, value_field, {})

        if not waterfall_data:
            return self._fail("缺少 waterfall_data 参数，且无法从上游归因结果或 DataFrame 推导")

        categories: list[str] = []
        base_series: list[float] = []    # invisible base (stack)
        value_series: list[dict[str, Any]] = []  # visible bar
        running = 0.0

        for i, item in enumerate(waterfall_data):
            name = item.get("name", f"项{i}")
            try:
                value = float(item.get("value", 0))
            except Exception:
                value = 0.0
            categories.append(name)

            is_first = i == 0
            is_last = i == len(waterfall_data) - 1

            if is_first or is_last:
                base_series.append(0)
                value_series.append({
                    "value": round(abs(value), 2),
                    "itemStyle": {"color": COLOR_BASE},
                })
                if is_first:
                    running = value
            else:
                if value >= 0:
                    base_series.append(round(running, 2))
                    value_series.append({
                        "value": round(value, 2),
                        "itemStyle": {"color": COLOR_POSITIVE},
                    })
                    running += value
                else:
                    running += value
                    base_series.append(round(max(running, 0), 2))
                    value_series.append({
                        "value": round(abs(value), 2),
                        "itemStyle": {"color": COLOR_NEGATIVE},
                    })

        # Skip gate: if every incremental value rounds to 0, the chart is noise
        check_series = [
            {"data": [v["value"] for v in value_series]},
        ]
        if not has_valid_series_data(check_series):
            return ToolOutput(
                tool_id=self.tool_id, status="skipped", output_type="chart",
                error_message="waterfall: 所有增量值均为 0",
                metadata={"skip_reason": "ALL_ZERO", "chart_subtype": "waterfall"},
            )

        option = {
            "title": {"text": parsed["title"] or intent or "归因瀑布图", "left": "center",
                      "textStyle": {"color": COLOR_BASE}},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "xAxis": {"type": "category", "data": categories},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "name": "基准",
                    "type": "bar",
                    "stack": "waterfall",
                    "itemStyle": {"borderColor": "transparent", "color": "transparent"},
                    "emphasis": {"itemStyle": {"borderColor": "transparent", "color": "transparent"}},
                    "data": base_series,
                },
                {
                    "name": "变化量",
                    "type": "bar",
                    "stack": "waterfall",
                    "label": {"show": True, "position": "top"},
                    "data": value_series,
                },
            ],
        }

        return ToolOutput(
            tool_id=self.tool_id,
            status="success",
            output_type="chart",
            data=option,
            metadata={
                "chart_type": "waterfall",
                "item_count": len(waterfall_data),
            },
        )

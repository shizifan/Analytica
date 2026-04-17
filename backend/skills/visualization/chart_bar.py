"""Bar Chart Skill — generates ECharts bar chart option JSON."""
from __future__ import annotations

from typing import Any

import pandas as pd

from backend.skills.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.skills.registry import register_skill

THEME_PRIMARY = "#1E3A5F"
THEME_ACCENT = "#F0A500"
SERIES_COLORS = [THEME_PRIMARY, THEME_ACCENT, "#E85454", "#4CAF50"]


@register_skill("skill_chart_bar", SkillCategory.VISUALIZATION, "柱状图生成（ECharts option JSON）",
                input_spec="data_ref + title + category_column + value_columns",
                output_spec="ECharts option JSON")
class BarChartSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        params = inp.params
        data_ref = params.get("data_ref")
        title = params.get("title", "柱状图")
        category_column = params.get("category_column", "")
        value_columns = params.get("value_columns", [])

        # Normalize: LLM sometimes passes list instead of str
        if isinstance(data_ref, list):
            data_ref = data_ref[0] if data_ref else None

        df = None
        if data_ref and data_ref in context:
            ctx_out = context[data_ref]
            if hasattr(ctx_out, "data"):
                df = ctx_out.data
            elif isinstance(ctx_out, dict):
                df = ctx_out.get("data")
        if not isinstance(df, pd.DataFrame) or df.empty:
            # Try context_refs
            for ref in (inp.context_refs or []):
                if ref in context:
                    ctx_out = context[ref]
                    ref_data = ctx_out.data if hasattr(ctx_out, "data") else ctx_out
                    if isinstance(ref_data, pd.DataFrame) and not ref_data.empty:
                        df = ref_data
                        break
        if not isinstance(df, pd.DataFrame) or df.empty:
            # Deep fallback: scan full context for any DataFrame
            for tid, ctx_out in context.items():
                ref_data = ctx_out.data if hasattr(ctx_out, "data") else ctx_out
                if isinstance(ref_data, pd.DataFrame) and not ref_data.empty:
                    df = ref_data
                    break

        if not isinstance(df, pd.DataFrame) or df.empty:
            return self._fail("无法获取有效的 DataFrame 数据")

        # Auto-detect category_column if not specified or not found
        if not category_column or category_column not in df.columns:
            for col in df.columns:
                if not pd.api.types.is_numeric_dtype(df[col]):
                    category_column = col
                    break
        if not category_column or category_column not in df.columns:
            return self._fail(f"分类列 '{category_column}' 不存在")

        # Auto-detect value_columns if not specified
        if not value_columns:
            value_columns = [c for c in df.columns if c != category_column and pd.api.types.is_numeric_dtype(df[c])]

        x_data = [str(v) for v in df[category_column].tolist()]

        series = []
        for i, col in enumerate(value_columns):
            if col not in df.columns:
                continue
            series.append({
                "name": col,
                "type": "bar",
                "data": [round(float(v), 2) if pd.notna(v) else None for v in df[col]],
                "itemStyle": {"color": SERIES_COLORS[i % len(SERIES_COLORS)]},
            })

        # Fallback: if LLM-specified columns didn't match, auto-detect numeric columns
        if not series:
            fallback_cols = [c for c in df.columns if c != category_column and pd.api.types.is_numeric_dtype(df[c])]
            for i, col in enumerate(fallback_cols):
                series.append({
                    "name": col,
                    "type": "bar",
                    "data": [round(float(v), 2) if pd.notna(v) else None for v in df[col]],
                    "itemStyle": {"color": SERIES_COLORS[i % len(SERIES_COLORS)]},
                })

        if not series:
            return self._fail("无有效的数值列")

        option = {
            "title": {"text": title, "left": "center", "textStyle": {"color": THEME_PRIMARY}},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "legend": {"data": [s["name"] for s in series], "bottom": 0},
            "xAxis": {"type": "category", "data": x_data},
            "yAxis": {"type": "value"},
            "series": series,
        }

        return SkillOutput(
            skill_id=self.skill_id,
            status="success",
            output_type="chart",
            data=option,
            metadata={"chart_type": "bar", "series_count": len(series)},
        )

"""Waterfall Chart Skill — generates ECharts waterfall chart for attribution visualization."""
from __future__ import annotations

from typing import Any

from backend.skills.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.skills.registry import register_skill

COLOR_BASE = "#1E3A5F"     # deep blue for base/total
COLOR_POSITIVE = "#F0A500"  # amber for positive
COLOR_NEGATIVE = "#E85454"  # red for negative


@register_skill("skill_chart_waterfall", SkillCategory.VISUALIZATION, "瀑布图生成（归因可视化）",
                input_spec="waterfall_data + title",
                output_spec="ECharts option JSON")
class WaterfallChartSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        params = inp.params
        waterfall_data = params.get("waterfall_data", [])
        title = params.get("title", "归因瀑布图")

        # If waterfall_data not in params, try to find it in context_refs or full context
        if not waterfall_data:
            refs_to_check = inp.context_refs if inp.context_refs else list(context.keys())
            for ref in refs_to_check:
                if ref in context:
                    ctx_out = context[ref]
                    data = ctx_out.data if hasattr(ctx_out, "data") else ctx_out
                    if isinstance(data, dict) and "waterfall_data" in data:
                        waterfall_data = data["waterfall_data"]
                        break

        if not waterfall_data:
            return self._fail("缺少 waterfall_data 参数")

        categories = []
        base_series = []   # invisible base (stack)
        value_series = []  # visible bar
        running = 0

        for i, item in enumerate(waterfall_data):
            name = item.get("name", f"项{i}")
            value = item.get("value", 0)
            direction = item.get("direction", "")
            categories.append(name)

            is_first = i == 0
            is_last = i == len(waterfall_data) - 1

            if is_first or is_last:
                # Base or total: full bar from 0
                base_series.append(0)
                value_series.append({
                    "value": abs(value),
                    "itemStyle": {"color": COLOR_BASE},
                })
                if is_first:
                    running = value
            else:
                # Incremental bar
                if value >= 0:
                    base_series.append(running)
                    value_series.append({
                        "value": value,
                        "itemStyle": {"color": COLOR_POSITIVE},
                    })
                    running += value
                else:
                    running += value
                    base_series.append(max(running, 0))
                    value_series.append({
                        "value": abs(value),
                        "itemStyle": {"color": COLOR_NEGATIVE},
                    })

        option = {
            "title": {"text": title, "left": "center", "textStyle": {"color": COLOR_BASE}},
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
            "xAxis": {"type": "category", "data": categories},
            "yAxis": {"type": "value"},
            "series": [
                {
                    "name": "base",
                    "type": "bar",
                    "stack": "waterfall",
                    "itemStyle": {"borderColor": "transparent", "color": "transparent"},
                    "emphasis": {"itemStyle": {"borderColor": "transparent", "color": "transparent"}},
                    "data": base_series,
                },
                {
                    "name": "value",
                    "type": "bar",
                    "stack": "waterfall",
                    "label": {"show": True, "position": "top"},
                    "data": value_series,
                },
            ],
        }

        return SkillOutput(
            skill_id=self.skill_id,
            status="success",
            output_type="chart",
            data=option,
            metadata={"chart_type": "waterfall", "item_count": len(waterfall_data)},
        )

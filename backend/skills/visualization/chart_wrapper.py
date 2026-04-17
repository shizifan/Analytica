"""Dashboard Skill — combines multiple charts into a single HTML page."""
from __future__ import annotations

from typing import Any

from backend.skills.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.skills.registry import register_skill


@register_skill("skill_dashboard", SkillCategory.VISUALIZATION, "仪表盘（多图表组合 HTML）",
                input_spec="chart_refs + title",
                output_spec="组合 HTML 页面")
class DashboardSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        params = inp.params
        chart_refs = params.get("chart_refs", [])
        title = params.get("title", "数据仪表盘")

        charts_html = []
        for ref in chart_refs:
            if ref in context:
                ctx_out = context[ref]
                data = ctx_out.data if hasattr(ctx_out, "data") else (ctx_out.get("data") if isinstance(ctx_out, dict) else None)
                if data:
                    import json
                    chart_id = f"chart_{ref}"
                    charts_html.append(
                        f'<div id="{chart_id}" style="width:100%;height:400px;margin-bottom:20px;"></div>\n'
                        f'<script>echarts.init(document.getElementById("{chart_id}")).setOption({json.dumps(data, ensure_ascii=False)});</script>'
                    )

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>body{{font-family:'Microsoft YaHei',sans-serif;padding:20px;background:#f5f5f5;}}
h1{{color:#1E3A5F;text-align:center;}}.chart-container{{max-width:1200px;margin:0 auto;}}</style>
</head><body><h1>{title}</h1><div class="chart-container">
{''.join(charts_html) if charts_html else '<p>暂无图表数据</p>'}
</div></body></html>"""

        return SkillOutput(
            skill_id=self.skill_id,
            status="success",
            output_type="file",
            data=html,
            metadata={"chart_count": len(charts_html), "format": "html"},
        )

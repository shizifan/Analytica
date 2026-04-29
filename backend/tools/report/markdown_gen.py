"""Markdown Report Generation Skill — Step 3 (outline pipeline).

Output is byte-for-byte equivalent to the previous deterministic builder
(guarded by ``tests/contract/test_report_outputs_baseline.py``). All
rendering helpers now live in
``backend.tools.report._renderers.markdown``.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tools.report._block_renderer import render_outline
from backend.tools.report._outline_planner import plan_outline
from backend.tools.report._renderers.markdown import MarkdownBlockRenderer

logger = logging.getLogger("analytica.tools.report_markdown")


@register_tool("tool_report_markdown", ToolCategory.REPORT, "Markdown 报告生成（.md 文件）",
                input_spec="report_metadata + report_structure + 上游数据/图表引用",
                output_spec="Markdown 文件路径")
class MarkdownReportTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        try:
            outline = await plan_outline(
                inp.params, context,
                task_order=inp.params.get("_task_order"),
                intent=inp.params.get("intent", ""),
                task_id=inp.params.get("__task_id__", ""),
                span_emit=inp.span_emit,
            )

            renderer = MarkdownBlockRenderer()
            md = render_outline(outline, renderer)

            meta: dict[str, Any] = {
                "format": "markdown",
                "title": outline.metadata.get("title", ""),
                "char_count": len(md),
                "line_count": len(md.splitlines()),
                "mode": outline.planner_mode,
            }
            if outline.degradations:
                meta["degradations"] = outline.degradations
            return ToolOutput(
                tool_id=self.tool_id,
                status="success",
                output_type="file",
                data=md,
                metadata=meta,
            )

        except Exception as e:
            logger.exception("Markdown generation failed: %s", e)
            return self._fail(str(e))

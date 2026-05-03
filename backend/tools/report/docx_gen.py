"""DOCX Report Generation Tool — outline pipeline + deterministic rendering.

The outline planner (LLM) decides what blocks go where; a deterministic
``render_outline`` loop walks the result and calls the renderer's emit
methods. No LLM agent loop — the walk is purely mechanical.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tools.report._block_renderer import render_outline
from backend.tools.report._outline_planner import plan_outline
from backend.tools.report._renderers.docx import DocxBlockRenderer
from backend.tools.report._theme import get_theme

logger = logging.getLogger("analytica.tools.report_docx")


@register_tool("tool_report_docx", ToolCategory.REPORT, "Word 报告生成（.docx 文件）",
                input_spec="report_metadata + report_structure + 上游数据/图表引用",
                output_spec="DOCX 文件路径")
class DocxReportTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        try:
            outline = await plan_outline(
                inp.params, context,
                task_order=inp.params.get("_task_order"),
                intent=inp.params.get("intent", ""),
                task_id=inp.params.get("__task_id__", ""),
                span_emit=inp.span_emit,
            )

            theme = get_theme(
                (inp.params.get("report_metadata") or {}).get("theme"),
            )
            renderer = DocxBlockRenderer(theme=theme)
            docx_bytes = render_outline(outline, renderer)

            meta: dict[str, Any] = {
                "format": "docx",
                "title": outline.metadata.get("title", ""),
                "file_size_bytes": len(docx_bytes),
                "mode": "deterministic",
            }
            if outline.degradations:
                meta["degradations"] = outline.degradations
            return ToolOutput(
                tool_id=self.tool_id,
                status="success",
                output_type="file",
                data=docx_bytes,
                metadata=meta,
            )

        except Exception as e:
            logger.exception("DOCX generation failed: %s", e)
            return self._fail(str(e))

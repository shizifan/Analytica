"""PPTX Report Generation Tool — outline pipeline + PptxGenJS native charts.

Single pipeline: ``plan_outline`` (LLM) → ``render_outline`` (deterministic)
via ``PptxGenJSBlockRenderer``. Native editable PowerPoint charts via the
Node.js + pptxgenjs bridge are a **quality red line** — the python-pptx
fallback is removed. The bridge MUST be available; if not, the tool fails.

No LLM agent loop on this backend by design.
"""
from __future__ import annotations

import io
import logging
from typing import Any

from pptx import Presentation

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tools.report._block_renderer import render_outline
from backend.tools.report._outline_planner import plan_outline
from backend.tools.report._pptxgen_builder import check_pptxgen_available
from backend.tools.report._quality_reviewer import BLOCKING, review_pptx_output
from backend.tools.report._renderers.pptxgen import PptxGenJSBlockRenderer
from backend.tools.report._theme import get_theme

logger = logging.getLogger("analytica.tools.report_pptx")


@register_tool("tool_report_pptx", ToolCategory.REPORT, "PPTX 报告生成（封面/目录/图表/总结）",
                input_spec="report_metadata + report_structure + 上游数据/图表引用",
                output_spec="PPTX 文件字节")
class PptxReportTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        try:
            outline = await plan_outline(
                inp.params, context,
                task_order=inp.params.get("_task_order"),
                intent=inp.params.get("intent", ""),
                task_id=inp.params.get("__task_id__", ""),
                span_emit=inp.span_emit,
            )

            if not check_pptxgen_available():
                raise RuntimeError(
                    "PptxGenJS Node bridge is unavailable — "
                    "PPTX native charts are a quality red line. "
                    "Ensure Node.js and pptxgenjs are installed."
                )

            theme = get_theme(
                (inp.params.get("report_metadata") or {}).get("theme"),
            )
            renderer = PptxGenJSBlockRenderer(theme=theme)
            render_outline(outline, renderer)
            pptx_bytes = renderer.end_document()

            # PR-4: PPTX 后置质量审查
            review_result = review_pptx_output(
                pptx_bytes, outline=outline,
            )

            try:
                slide_count = len(Presentation(io.BytesIO(pptx_bytes)).slides)
            except Exception:
                slide_count = len(outline.sections) + 4

            meta: dict[str, Any] = {
                "format": "pptx",
                "title": outline.metadata.get("title", ""),
                "file_size_bytes": len(pptx_bytes),
                "mode": f"pptxgenjs_{outline.planner_mode}",
                "slide_count": slide_count,
                "sections": len(outline.sections),
                "review_passed": review_result.passed,
                "review_findings": [
                    {
                        "dimension": f.dimension,
                        "passed": f.passed,
                        "severity": f.severity,
                        "detail": f.detail,
                    }
                    for f in review_result.findings
                ],
            }
            if outline.degradations:
                meta["degradations"] = outline.degradations
            return ToolOutput(
                tool_id=self.tool_id,
                status="success",
                output_type="file",
                data=pptx_bytes,
                metadata=meta,
            )

        except Exception as e:
            logger.exception("PPTX generation failed: %s", e)
            return self._fail(str(e))

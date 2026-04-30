"""PPTX Report Generation Skill — Step 0 (Sprint 2 closure).

Single-pipeline architecture: ``plan_outline`` produces a ``ReportOutline``,
then a renderer is selected based on Node bridge availability:

  1. **PptxGenJSBlockRenderer** (Node + pptxgenjs) — produces native,
     editable PowerPoint charts. The Node side runs ``pptxgen_executor.js``
     and is fed a ``SlideCommand`` JSON stream.
  2. **PptxBlockRenderer** (python-pptx) — pure-Python fallback when
     Node / pptxgenjs is unavailable, or when the bridge raises. Charts
     degrade to data tables.

Either renderer consumes the same outline. The dual-path fork that lived
here through Sprint 1-2 (PptxGenJS taking ReportContent + python-pptx
taking outline) is gone — the chart-quality fallback now lives entirely
inside the renderer-selection step.

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
from backend.tools.report._renderers.pptx import PptxBlockRenderer
from backend.tools.report._renderers.pptxgen import PptxGenJSBlockRenderer
from backend.tools.report._theme import Theme, get_theme

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

            theme = get_theme(
                (inp.params.get("report_metadata") or {}).get("theme"),
            )
            pptx_bytes, mode = _render_pptx(outline, theme)

            try:
                slide_count = len(Presentation(io.BytesIO(pptx_bytes)).slides)
            except Exception:
                slide_count = len(outline.sections) + 4

            meta: dict[str, Any] = {
                "format": "pptx",
                "title": outline.metadata.get("title", ""),
                "file_size_bytes": len(pptx_bytes),
                "mode": mode,
                "slide_count": slide_count,
                "sections": len(outline.sections),
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


def _render_pptx(outline, theme: Theme) -> tuple[bytes, str]:
    """Render *outline* through the best available pipeline.

    Returns ``(pptx_bytes, mode_label)``. ``mode_label`` is surfaced in
    ToolOutput.metadata so downstream observability can distinguish
    native-chart runs from fallback runs.
    """
    if check_pptxgen_available():
        renderer = PptxGenJSBlockRenderer(theme=theme)
        try:
            render_outline(outline, renderer)
            pptx_bytes = renderer.end_document()
            logger.info(
                "PPTX generated via PptxGenJS bridge: %d bytes, %d sections",
                len(pptx_bytes), len(outline.sections),
            )
            return pptx_bytes, f"pptxgenjs_{outline.planner_mode}"
        except Exception as bridge_err:
            logger.warning(
                "PptxGenJS bridge failed (%s); falling back to python-pptx",
                bridge_err,
            )

    renderer = PptxBlockRenderer(theme=theme)
    render_outline(outline, renderer)
    pptx_bytes = renderer.end_document()
    return pptx_bytes, f"python_pptx_{outline.planner_mode}"

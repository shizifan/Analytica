"""PPTX Report Generation Skill — Step 5 (outline pipeline for fallback).

Generation strategy (in priority order):
  1. **PptxGenJS** (Node.js subprocess) — native PowerPoint charts.
     Still consumes the legacy ``ReportContent`` model; will be migrated
     to the outline pipeline as part of Sprint 3 visual work.
  2. **PptxBlockRenderer** (python-pptx, outline-driven) — pure-Python
     fallback that produces output structurally equivalent to the
     pre-refactor deterministic builder.

No LLM agent loop on this backend by design — the deterministic builders
already produce high-quality slides from structured data, making LLM
orchestration unnecessary overhead.
"""
from __future__ import annotations

import io
import logging
from typing import Any

from pptx import Presentation

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tools.report._block_renderer import render_outline
from backend.tools.report._kpi_extractor import extract_kpis_llm
from backend.tools.report._outline_planner import plan_outline
from backend.tools.report._renderers.pptx import PptxBlockRenderer

logger = logging.getLogger("analytica.tools.report_pptx")


@register_tool("tool_report_pptx", ToolCategory.REPORT, "PPTX 报告生成（封面/目录/图表/总结）",
                input_spec="report_metadata + report_structure + 上游数据/图表引用",
                output_spec="PPTX 文件字节")
class PptxReportTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        try:
            intent = inp.params.get("intent", "")
            task_id = inp.params.get("__task_id__", "")
            task_order = inp.params.get("_task_order")

            # ── Strategy 1: PptxGenJS (legacy ReportContent path) ──
            # Bypasses the outline planner — Sprint 3 visual work will
            # migrate this bridge. Until then it owns its own KPI
            # extraction + content collection.
            try:
                from backend.tools.report._pptxgen_builder import (
                    check_pptxgen_available,
                    render_to_pptx,
                )

                if check_pptxgen_available():
                    from backend.tools.report._content_collector import (
                        collect_and_associate,
                    )

                    kpi_cards = await extract_kpis_llm(
                        intent, context,
                        span_emit=inp.span_emit, task_id=task_id,
                    )
                    rc = collect_and_associate(
                        inp.params, context, task_order=task_order,
                    )
                    rc.kpi_cards = kpi_cards
                    pptx_bytes = render_to_pptx(rc)

                    try:
                        slide_count = len(
                            Presentation(io.BytesIO(pptx_bytes)).slides
                        )
                    except Exception:
                        slide_count = len(rc.sections) + 4

                    logger.info(
                        "PPTX generated via PptxGenJS: %d bytes, %d slides, "
                        "%d sections",
                        len(pptx_bytes), slide_count, len(rc.sections),
                    )
                    return ToolOutput(
                        tool_id=self.tool_id,
                        status="success",
                        output_type="file",
                        data=pptx_bytes,
                        metadata={
                            "format": "pptx",
                            "title": rc.title,
                            "file_size_bytes": len(pptx_bytes),
                            "mode": "pptxgenjs",
                            "slide_count": slide_count,
                            "sections": len(rc.sections),
                        },
                    )
                logger.info("PptxGenJS not available; using outline pipeline")
            except Exception as pptxgen_err:
                logger.warning(
                    "PptxGenJS render failed (%s); using outline pipeline",
                    pptxgen_err,
                )

            # ── Strategy 2: outline pipeline + python-pptx renderer ──
            outline = await plan_outline(
                inp.params, context,
                task_order=task_order, intent=intent,
                task_id=task_id, span_emit=inp.span_emit,
            )
            renderer = PptxBlockRenderer()
            render_outline(outline, renderer)
            pptx_bytes = renderer.end_document()

            try:
                slide_count = len(Presentation(io.BytesIO(pptx_bytes)).slides)
            except Exception:
                slide_count = len(outline.sections) + 4

            meta: dict[str, Any] = {
                "format": "pptx",
                "title": outline.metadata.get("title", ""),
                "file_size_bytes": len(pptx_bytes),
                "mode": f"python_pptx_{outline.planner_mode}",
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

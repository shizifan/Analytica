"""PPTX Report Generation Skill.

Generation strategy (in priority order):
  1. **PptxGenJS** (Node.js subprocess) — native PowerPoint charts, modern
     layouts with KPI callouts, two-column narrative+chart slides.
     Requires: ``node`` + ``pptxgenjs`` npm package.
  2. **python-pptx deterministic** — pure-Python fallback with the same
     slide structure but without native charts or advanced styling.

The LLM agent loop is intentionally removed for PPTX: the deterministic
builders now produce high-quality slides from the structured ReportContent
model, making LLM orchestration unnecessary overhead.
"""
from __future__ import annotations

import io
import logging
from typing import Any

from pptx import Presentation
from pptx.util import Inches

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tools.report._content_collector import (
    collect_and_associate,
    NarrativeItem, StatsTableItem, GrowthItem,
    ChartDataItem, DataFrameItem, ReportContent,
)
from backend.tools.report import _pptx_slides as S
from backend.tools.report import _theme as T
from backend.tools.report._kpi_extractor import extract_kpis_llm
from backend.tools._field_labels import metric_label

logger = logging.getLogger("analytica.tools.report_pptx")


# ---------------------------------------------------------------------------
# Python-pptx deterministic fallback
# ---------------------------------------------------------------------------

def _stats_to_text(summary_stats: dict[str, Any]) -> str:
    """Convert summary_stats dict to readable text for two-column layout."""
    lines: list[str] = []
    for col, vals in summary_stats.items():
        if not isinstance(vals, dict):
            continue
        mean = vals.get("mean")
        std = vals.get("std")
        if mean is not None:
            line = f"{col}：{metric_label('mean')} {mean:,.2f}"
            if std is not None:
                line += f"  {metric_label('std')} {std:,.2f}"
            lines.append(line)
    return "\n".join(lines) if lines else "暂无统计数据"


def _build_pptx_deterministic(prs: Presentation, report: ReportContent) -> None:
    """Build PPTX content using hardcoded slide ordering — the python-pptx fallback."""
    S.build_cover_slide(prs, report.title, report.author, report.date)
    S.build_toc_slide(prs, [s.name for s in report.sections])

    # KPI overview slide (python-pptx version)
    if report.kpi_cards:
        from pptx.util import Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN

        slide = prs.slides.add_slide(prs.slide_layouts[6])
        fill = slide.background.fill
        fill.solid()
        fill.fore_color.rgb = RGBColor(*T.RGB_BG_LIGHT)

        from backend.tools.report._pptx_slides import _add_textbox, _add_rect
        _add_textbox(slide, Inches(0.5), Inches(0.3), Inches(9), Inches(0.7),
                     "核心经营指标", font_size=22, bold=True,
                     color=T.RGB_PRIMARY, alignment=PP_ALIGN.LEFT)

        n = min(len(report.kpi_cards), 4)
        card_w = 8.0 / n
        for i, kpi in enumerate(report.kpi_cards[:n]):
            cx = 1.0 + i * card_w
            _add_rect(slide, Inches(cx), Inches(1.3), Inches(card_w - 0.2), Inches(4.5),
                      T.RGB_BG_LIGHT)
            _add_textbox(slide, Inches(cx + 0.1), Inches(1.5), Inches(card_w - 0.4), Inches(0.4),
                         kpi.label, font_size=10, color=T.RGB_NEUTRAL, alignment=PP_ALIGN.CENTER)
            color = T.RGB_POSITIVE if kpi.trend == "positive" else (
                T.RGB_NEGATIVE if kpi.trend == "negative" else T.RGB_PRIMARY)
            _add_textbox(slide, Inches(cx + 0.1), Inches(2.0), Inches(card_w - 0.4), Inches(1.2),
                         kpi.value, font_size=36, bold=True, color=color,
                         alignment=PP_ALIGN.CENTER, font_name=T.FONT_NUM)
            if kpi.sub:
                _add_textbox(slide, Inches(cx + 0.1), Inches(3.3), Inches(card_w - 0.4), Inches(0.4),
                             kpi.sub, font_size=9, color=T.RGB_NEUTRAL, alignment=PP_ALIGN.CENTER)

    for idx, section in enumerate(report.sections, 1):
        S.build_section_divider_slide(prs, idx, section.name)

        narratives = [it for it in section.items if isinstance(it, NarrativeItem)]
        stats_items = [it for it in section.items if isinstance(it, StatsTableItem)]
        growth_items = [it for it in section.items if isinstance(it, GrowthItem)]
        chart_items = [it for it in section.items if isinstance(it, ChartDataItem)]

        for gi in growth_items:
            S.build_kpi_cards_slide(prs, section.name, gi.growth_rates)

        if narratives and stats_items:
            nar_text = "\n\n".join(n.text for n in narratives)
            stats_text = _stats_to_text(stats_items[0].summary_stats)
            S.build_two_column_slide(prs, section.name, nar_text, stats_text)
            for si in stats_items:
                S.build_stats_table_slide(prs, f"{section.name} - 统计数据", si.summary_stats)
        elif narratives:
            nar_text = "\n\n".join(n.text for n in narratives)
            S.build_narrative_slide(prs, section.name, nar_text)
        elif stats_items:
            for si in stats_items:
                S.build_stats_table_slide(prs, f"{section.name} - 统计数据", si.summary_stats)

        for ci in chart_items:
            S.build_chart_table_slide(prs, ci.option)

    conclusions = []
    for si in report.summary_items:
        text = si.text
        conclusions.append(text[:120] + "..." if len(text) > 120 else text)
    if not conclusions:
        for sec in report.sections:
            for item in sec.items:
                if isinstance(item, NarrativeItem) and len(item.text) > 20:
                    conclusions.append(item.text[:100] + "...")
                    break
    if not conclusions:
        conclusions = ["数据分析完成，详见各章节内容"]

    S.build_summary_slide(prs, conclusions)
    S.build_thank_you_slide(prs)


# ---------------------------------------------------------------------------
# Skill
# ---------------------------------------------------------------------------

@register_tool("tool_report_pptx", ToolCategory.REPORT, "PPTX 报告生成（封面/目录/图表/总结）",
                input_spec="report_metadata + report_structure + 上游数据/图表引用",
                output_spec="PPTX 文件字节")
class PptxReportTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        try:
            intent = inp.params.get("intent", "")
            task_id = inp.params.get("__task_id__", "")

            report = collect_and_associate(
                inp.params, context,
                task_order=inp.params.get("_task_order"),
            )
            report.kpi_cards = await extract_kpis_llm(
                intent, context, span_emit=inp.span_emit, task_id=task_id,
            )

            # ── Strategy 1: PptxGenJS (native charts, modern layouts) ──
            try:
                from backend.tools.report._pptxgen_builder import (
                    render_to_pptx,
                    check_pptxgen_available,
                )
                if check_pptxgen_available():
                    pptx_bytes = render_to_pptx(report)
                    # Count slides for metadata (open with python-pptx, read-only)
                    try:
                        import io as _io
                        _slide_count = len(Presentation(_io.BytesIO(pptx_bytes)).slides)
                    except Exception:
                        _slide_count = len(report.sections) + 4  # cover+toc+summary+thanks
                    logger.info(
                        "PPTX generated via PptxGenJS: %d bytes, %d slides, %d sections",
                        len(pptx_bytes), _slide_count, len(report.sections),
                    )
                    return ToolOutput(
                        tool_id=self.tool_id,
                        status="success",
                        output_type="file",
                        data=pptx_bytes,
                        metadata={
                            "format": "pptx",
                            "title": report.title,
                            "file_size_bytes": len(pptx_bytes),
                            "mode": "pptxgenjs",
                            "slide_count": _slide_count,
                            "sections": len(report.sections),
                        },
                    )
                else:
                    logger.info("PptxGenJS not available; using python-pptx fallback")
            except Exception as pptxgen_err:
                logger.warning(
                    "PptxGenJS render failed (%s); falling back to python-pptx", pptxgen_err
                )

            # ── Strategy 2: python-pptx deterministic ──
            prs = Presentation()
            prs.slide_width = Inches(T.SLIDE_WIDTH)
            prs.slide_height = Inches(T.SLIDE_HEIGHT)
            _build_pptx_deterministic(prs, report)

            buffer = io.BytesIO()
            prs.save(buffer)
            pptx_bytes = buffer.getvalue()

            meta: dict[str, Any] = {
                "format": "pptx",
                "slide_count": len(prs.slides),
                "title": report.title,
                "file_size_bytes": len(pptx_bytes),
                "mode": "python_pptx_fallback",
            }
            if report.degradations:
                meta["degradations"] = report.degradations
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

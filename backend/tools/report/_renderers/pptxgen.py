"""PptxGenJSBlockRenderer — Step 0.2 of Sprint 2 closure.

Implements the BlockRenderer protocol on top of the SlideCommand DSL.
Each ``emit_*`` method appends to ``self._commands``; ``end_document``
serialises the list and hands it to the Node executor (Step 0.3) which
returns the .pptx bytes.

Layout parity:
- Slide canvas matches ``_theme`` (10 × 7.5 inches, same as ``_pptx_slides``).
- Slide composition follows the same section-buffer logic as
  ``_renderers/pptx.py:PptxBlockRenderer`` so output structure aligns —
  the difference is downstream: PptxGenJS produces native, editable
  PowerPoint charts; python-pptx produces table fallbacks.

Failure handling:
- ``end_document`` may raise ``RuntimeError`` if the Node executor fails
  (missing node, executor crash, timeout). Caller (`pptx_gen.py`) must
  catch and fall back to ``PptxBlockRenderer`` (python-pptx).
"""
from __future__ import annotations

from typing import Any

from backend.tools._field_labels import metric_label
from backend.tools.report import _theme as T
from backend.tools.report._block_renderer import BlockRendererBase
from backend.tools.report._outline import KPIItem
from backend.tools.report._outline import (
    Asset,
    ChartBlock,
    ChartTablePairBlock,
    ComparisonGridBlock,
    GrowthIndicatorsBlock,
    KpiRowBlock,
    OutlineSection,
    ParagraphBlock,
    ReportOutline,
    SectionCoverBlock,
    StatsAsset,
    TableBlock,
)
from backend.tools.report._pptxgen_builder import echarts_to_pptxgen
from backend.tools.report._pptxgen_commands import (
    AddChart,
    AddShape,
    AddTable,
    AddText,
    NewSlide,
    SlideCommand,
    serialize_commands,
)
from backend.tools.report._pptxgen_runtime import run_pptxgen_executor


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

def _hex(rgb: tuple[int, int, int]) -> str:
    return f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


_C = {
    "primary": _hex(T.RGB_PRIMARY),
    "secondary": _hex(T.RGB_SECONDARY),
    "accent": _hex(T.RGB_ACCENT),
    "positive": _hex(T.RGB_POSITIVE),
    "negative": _hex(T.RGB_NEGATIVE),
    "neutral": _hex(T.RGB_NEUTRAL),
    "bg_light": _hex(T.RGB_BG_LIGHT),
    "white": _hex(T.RGB_WHITE),
    "text_dark": _hex(T.RGB_TEXT_DARK),
}


# ---------------------------------------------------------------------------
# Stats text helper (mirrors _renderers/pptx.py)
# ---------------------------------------------------------------------------

def _stats_to_text(summary_stats: dict[str, Any]) -> str:
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


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class PptxGenJSBlockRenderer(BlockRendererBase):
    """Renders an outline into a SlideCommand stream and runs the Node bridge.

    Step 0.2 is the Python-side; Step 0.3 ships the matching JS executor.
    """

    _step_label = "Step 0.2"

    def __init__(self, theme=None) -> None:  # noqa: ANN001
        super().__init__(theme=theme)
        self._commands: list[SlideCommand] = []

        self._title: str = ""
        self._numbered_count: int = 0
        self._is_appendix: bool = False
        self._current_section_name: str = ""

        # Per-section buffers — flushed in end_section
        self._narratives: list[str] = []
        self._stats: list[dict[str, Any]] = []
        self._growth: list[dict[str, Any]] = []
        self._charts: list[dict[str, Any]] = []

        # Cross-section state
        self._appendix_paragraphs: list[str] = []
        self._all_narratives: list[str] = []  # for fallback summary

    # ---- Public hook for tests --------------------------------------

    @property
    def commands(self) -> list[SlideCommand]:
        """Snapshot of accumulated commands (used by unit tests)."""
        return list(self._commands)

    # ---- Lifecycle ---------------------------------------------------

    def begin_document(self, outline: ReportOutline) -> None:
        self._title = outline.metadata.get("title", "")
        author = outline.metadata.get("author", "")
        date = outline.metadata.get("date", "")

        self._add_cover_slide(self._title, author, date)

        toc_names = [s.name for s in outline.sections if s.role != "appendix"]
        if toc_names:
            self._add_toc_slide(toc_names)

        if outline.kpi_summary:
            self._add_kpi_overview_slide(outline.kpi_summary)

    def end_document(self) -> bytes:
        """Serialise commands and invoke the Node bridge for .pptx bytes.

        Raises ``RuntimeError`` on any executor failure — pptx_gen.py
        catches and falls back to PptxBlockRenderer.
        """
        payload = serialize_commands(self._commands)
        return run_pptxgen_executor(payload)

    def begin_section(self, section: OutlineSection, index: int) -> None:
        if section.role == "appendix":
            self._is_appendix = True
            self._appendix_paragraphs = []
        else:
            self._is_appendix = False
            self._numbered_count += 1
            self._current_section_name = section.name
            # Phase 3.1: divider slide is emitted by ``emit_section_cover``
            # (driven by the SectionCoverBlock the legacy converter / LLM
            # planner inserts). begin_section keeps state-only duties.
            self._narratives = []
            self._stats = []
            self._growth = []
            self._charts = []

    def end_section(self, section: OutlineSection, index: int) -> None:
        if self._is_appendix:
            self._render_summary_and_thanks()
        else:
            self._render_section_combo()

    # ---- Block emitters ---------------------------------------------

    def emit_kpi_row(self, block: KpiRowBlock) -> None:
        # Mid-section KPI rows are not represented (only kpi_summary above sec 1).
        return None

    def emit_paragraph(self, block: ParagraphBlock) -> None:
        # Phase 4.1 — same emoji-prefix approach as PptxBlockRenderer
        # (buffer mode preserved). Phase 5.1 will introduce a standalone
        # callout shape for higher visual prominence.
        text = block.text
        if block.style == "callout-warn":
            text = f"⚠ 注意: {text}"
        elif block.style == "callout-info":
            text = f"💡 提示: {text}"
        if self._is_appendix:
            self._appendix_paragraphs.append(text)
        else:
            self._narratives.append(text)
            self._all_narratives.append(text)

    def emit_table(self, block: TableBlock, asset: Asset) -> None:
        if isinstance(asset, StatsAsset):
            self._stats.append(asset.summary_stats)
        # TableAsset (DataFrame) — PptxGenJS path also skips, matching legacy.

    def emit_chart(self, block: ChartBlock, asset: Asset) -> None:
        option = getattr(asset, "option", None)
        if isinstance(option, dict):
            self._charts.append(option)

    def emit_chart_table_pair(
        self,
        block: ChartTablePairBlock,
        chart_asset: Asset,
        table_asset: Asset,
    ) -> None:
        """Phase 3.3 — dedicated side-by-side slide.

        Layout=h: chart left ~60% / table right ~40%
        Layout=v: chart top / table bottom (50/50)

        Skips the per-section narrative buffer entirely so the pair is
        rendered immediately, regardless of section composition.
        """
        chart_option = getattr(chart_asset, "option", None)
        if not isinstance(chart_option, dict):
            return
        spec = echarts_to_pptxgen(chart_option)
        if spec is None:
            return  # chart type not natively representable; pair degraded

        title = spec.get("title") or self._current_section_name or "对比分析"
        layout = block.layout if block.layout in ("h", "v") else "h"

        self._commands.append(NewSlide())
        self._commands.append(AddText(
            x=0.5, y=0.3, w=9, h=0.7, text=title,
            font_size=T.SIZE_H2, bold=True,
            color=_C["primary"], font_name=T.FONT_CN,
        ))

        if layout == "h":
            chart_x, chart_y, chart_w, chart_h = 0.5, 1.2, 5.6, 5.5
            tbl_x, tbl_y, tbl_w, tbl_h = 6.3, 1.2, 3.2, 5.5
        else:  # vertical
            chart_x, chart_y, chart_w, chart_h = 0.5, 1.2, 9.0, 3.0
            tbl_x, tbl_y, tbl_w, tbl_h = 0.5, 4.4, 9.0, 2.5

        # Chart half
        self._commands.append(AddChart(
            x=chart_x, y=chart_y, w=chart_w, h=chart_h,
            chart_type=spec["type"], data=spec["data"],
            options=spec["options"],
        ))

        # Table half — only StatsAsset can be rendered as a table here;
        # TableAsset (DataFrame) skipped to match legacy behaviour.
        from backend.tools.report._outline import StatsAsset as _StatsAsset
        if isinstance(table_asset, _StatsAsset):
            self._add_chart_table_pair_stats(
                tbl_x, tbl_y, tbl_w, tbl_h, table_asset.summary_stats,
            )

    def _add_chart_table_pair_stats(
        self, x: float, y: float, w: float, h: float,
        summary_stats: dict[str, Any],
    ) -> None:
        """Helper — flatten summary_stats into an AddTable for the
        right-hand column of a chart_table_pair slide."""
        if not summary_stats:
            return
        # Same flattening logic as _add_stats_table_slide
        first_val = next(iter(summary_stats.values()))
        if isinstance(first_val, dict) and not any(
            k in first_val for k in ("mean", "median", "std", "min", "max")
        ):
            flat: dict[str, dict] = {}
            for gk, cols in summary_stats.items():
                if isinstance(cols, dict):
                    for cn, metrics in cols.items():
                        flat[f"{gk}/{cn}"] = (
                            metrics if isinstance(metrics, dict) else {}
                        )
            summary_stats = flat if flat else summary_stats

        metrics = ["mean", "median", "std", "min", "max"]
        col_names = [c for c, v in summary_stats.items() if isinstance(v, dict)]
        if not col_names:
            return

        header_row = [
            {"text": "指标", "bold": True,
             "fill": _C["primary"], "color": _C["white"]},
        ] + [
            {"text": metric_label(m), "bold": True,
             "fill": _C["primary"], "color": _C["white"]}
            for m in metrics
        ]
        rows: list[list[dict[str, Any]]] = [header_row]
        for col in col_names:
            vals = summary_stats[col]
            row = [{"text": col, "bold": True}]
            for m in metrics:
                v = vals.get(m)
                row.append({"text": (
                    f"{v:,.2f}" if isinstance(v, (int, float)) else "-"
                )})
            rows.append(row)

        self._commands.append(AddTable(
            x=x, y=y, w=w, h=h,
            rows=rows,
            options={"fontSize": 9, "fontFace": T.FONT_NUM},
        ))

    def emit_comparison_grid(self, block: ComparisonGridBlock) -> None:
        """Phase 3.2 — render a dedicated comparison-grid slide.

        Layout: N equal-width column cards (rounded + shadow), each with
        a coloured title bar and a bulleted item list. Common use case:
        "短期 / 中期 / 长期" recommendations from the LLM planner.
        """
        if not block.columns:
            return

        # Anchor a fresh slide so the grid stands alone visually.
        self._commands.append(NewSlide(background=_C["bg_light"]))

        # Slide title (use section name if mid-section context exists,
        # else a generic header)
        slide_title = self._current_section_name or "对比分析"
        self._commands.append(AddText(
            x=0.5, y=0.3, w=9, h=0.7, text=slide_title,
            font_size=T.SIZE_H2, bold=True,
            color=_C["primary"], font_name=T.FONT_CN, alignment="left",
        ))

        n = min(len(block.columns), 4)  # cap visual at 4 columns
        margin = 0.6
        gap = 0.2
        usable = 10 - 2 * margin - gap * (n - 1)
        col_w = max(usable / n, 1.5)
        col_x_start = margin
        col_y = 1.3
        col_h = 5.5

        title_bar_h = 0.7
        for i, col in enumerate(block.columns[:n]):
            cx = col_x_start + i * (col_w + gap)
            # Card background — rounded with shadow (Phase 3.5 capability)
            self._commands.append(AddShape(
                x=cx, y=col_y, w=col_w, h=col_h,
                shape="rounded_rect", fill=_C["white"],
                rect_radius=0.04, shadow=True,
            ))
            # Title bar — primary-coloured strip across the top
            self._commands.append(AddShape(
                x=cx, y=col_y, w=col_w, h=title_bar_h,
                shape="rect", fill=_C["primary"],
            ))
            # Title text
            self._commands.append(AddText(
                x=cx + 0.1, y=col_y + 0.1, w=col_w - 0.2, h=title_bar_h - 0.2,
                text=col.title, font_size=14, bold=True,
                color=_C["white"], font_name=T.FONT_CN, alignment="center",
            ))
            # Items — bulleted list under the title bar
            items_text = "\n".join(f"• {it}" for it in col.items[:6])
            if items_text:
                self._commands.append(AddText(
                    x=cx + 0.2, y=col_y + title_bar_h + 0.15,
                    w=col_w - 0.4, h=col_h - title_bar_h - 0.3,
                    text=items_text, font_size=11,
                    color=_C["text_dark"], font_name=T.FONT_CN,
                ))

    def emit_growth_indicators(self, block: GrowthIndicatorsBlock) -> None:
        if block.growth_rates:
            self._growth.append(block.growth_rates)

    def emit_section_cover(self, block: SectionCoverBlock) -> None:
        """Emit the section divider slide via SlideCommand stream.
        Phase 3.1 makes this the sole owner of the divider visual."""
        self._add_section_divider_slide(block.index, block.title)

    # ---- Slide-level command builders -------------------------------

    def _add_cover_slide(self, title: str, author: str, date: str) -> None:
        self._commands.append(NewSlide(background=_C["primary"]))
        self._commands.append(AddText(
            x=1, y=2, w=8, h=1.5, text=title,
            font_size=T.SIZE_TITLE, bold=True,
            color=_C["white"], font_name=T.FONT_CN,
            alignment="center",
        ))
        self._commands.append(AddText(
            x=1, y=3.5, w=8, h=0.8, text=f"编制：{author}",
            font_size=18,
            color=_C["accent"], font_name=T.FONT_CN,
            alignment="center",
        ))
        self._commands.append(AddText(
            x=1, y=4.5, w=8, h=0.5, text=date,
            font_size=14,
            color=_C["white"], font_name=T.FONT_CN,
            alignment="center",
        ))

    def _add_toc_slide(self, sections: list[str]) -> None:
        self._commands.append(NewSlide())
        self._commands.append(AddText(
            x=0.5, y=0.3, w=9, h=0.8, text="目  录",
            font_size=24, bold=True,
            color=_C["primary"], font_name=T.FONT_CN,
            alignment="center",
        ))
        bar_h = min(len(sections) * 0.6, 5.5)
        self._commands.append(AddShape(
            x=1.2, y=1.3, w=0.08, h=bar_h,
            shape="rect", fill=_C["accent"],
        ))
        for i, name in enumerate(sections[:10]):
            self._commands.append(AddText(
                x=1.5, y=1.3 + i * 0.55, w=7, h=0.5,
                text=f"{i + 1}.  {name}",
                font_size=16, color=_C["primary"], font_name=T.FONT_CN,
            ))

    def _add_kpi_overview_slide(self, kpis: list[KPIItem]) -> None:
        """Phase 3.5 — modernised KPI cards: rounded corners + drop
        shadow + theme-aligned accent stripe. Pre-Phase-3.5 code used
        flat ``rect`` cards on a uniform light background; new layout
        uses white cards with shadow against a slightly darker page."""
        self._commands.append(NewSlide(background=_C["bg_light"]))
        self._commands.append(AddText(
            x=0.5, y=0.3, w=9, h=0.7, text="核心经营指标",
            font_size=22, bold=True,
            color=_C["primary"], font_name=T.FONT_CN, alignment="left",
        ))
        n = min(len(kpis), 4)
        if n == 0:
            return

        # Card dimensions tuned for 1-4 KPIs filling the visible canvas.
        card_w = 8.0 / n
        card_radius = 0.06  # ~6% of card width — subtle rounded corners
        accent_stripe_h = 0.12  # bottom accent bar tinted by trend

        for i, kpi in enumerate(kpis[:n]):
            cx = 1.0 + i * card_w

            # Trend colour drives both value text and accent stripe
            if kpi.trend == "positive":
                trend_color = _C["positive"]
            elif kpi.trend == "negative":
                trend_color = _C["negative"]
            else:
                trend_color = _C["accent"]

            # Card body — white rounded card with shadow
            self._commands.append(AddShape(
                x=cx, y=1.3, w=card_w - 0.2, h=4.5,
                shape="rounded_rect", fill=_C["white"],
                rect_radius=card_radius, shadow=True,
            ))
            # Bottom accent stripe — visual hierarchy cue per trend
            self._commands.append(AddShape(
                x=cx, y=1.3 + 4.5 - accent_stripe_h,
                w=card_w - 0.2, h=accent_stripe_h,
                shape="rect", fill=trend_color,
            ))
            # Label
            self._commands.append(AddText(
                x=cx + 0.1, y=1.5, w=card_w - 0.4, h=0.4,
                text=kpi.label,
                font_size=11, bold=True, color=_C["neutral"],
                font_name=T.FONT_CN, alignment="center",
            ))
            # Value (trend-coloured)
            self._commands.append(AddText(
                x=cx + 0.1, y=2.2, w=card_w - 0.4, h=1.2,
                text=kpi.value, font_size=36, bold=True,
                color=trend_color, font_name=T.FONT_NUM, alignment="center",
            ))
            if kpi.sub:
                self._commands.append(AddText(
                    x=cx + 0.1, y=3.6, w=card_w - 0.4, h=0.4,
                    text=kpi.sub, font_size=9,
                    color=_C["neutral"], font_name=T.FONT_CN,
                    alignment="center",
                ))

    def _add_section_divider_slide(self, number: int, title: str) -> None:
        self._commands.append(NewSlide(background=_C["primary"]))
        self._commands.append(AddText(
            x=1, y=1.5, w=3, h=2, text=f"{number:02d}",
            font_size=72, bold=True,
            color=_C["accent"], font_name=T.FONT_NUM,
        ))
        self._commands.append(AddText(
            x=1, y=3.8, w=8, h=1, text=title,
            font_size=T.SIZE_H1, bold=True,
            color=_C["white"], font_name=T.FONT_CN,
        ))
        self._commands.append(AddShape(
            x=1, y=4.8, w=2, h=0.06,
            shape="rect", fill=_C["accent"],
        ))

    def _add_narrative_slide(self, title: str, text: str) -> None:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        chunk_size = 12
        chunks = [lines[i:i + chunk_size] for i in range(0, len(lines), chunk_size)]
        if not chunks:
            chunks = [["（暂无详细内容）"]]
        for ci, chunk in enumerate(chunks):
            self._commands.append(NewSlide())
            self._commands.append(AddShape(
                x=0.3, y=0.3, w=0.08, h=6.9,
                shape="rect", fill=_C["accent"],
            ))
            suffix = f" ({ci+1}/{len(chunks)})" if len(chunks) > 1 else ""
            self._commands.append(AddText(
                x=0.6, y=0.3, w=9, h=0.8,
                text=f"{title}{suffix}",
                font_size=T.SIZE_H2, bold=True,
                color=_C["primary"], font_name=T.FONT_CN,
            ))
            joined = "\n".join(chunk)
            self._commands.append(AddText(
                x=0.8, y=1.3, w=8.6, h=5.8, text=joined,
                font_size=14, color=_C["text_dark"], font_name=T.FONT_CN,
            ))

    def _add_two_column_slide(
        self, title: str, left_text: str, right_text: str,
    ) -> None:
        self._commands.append(NewSlide())
        self._commands.append(AddText(
            x=0.5, y=0.3, w=9, h=0.8, text=title,
            font_size=T.SIZE_H2, bold=True,
            color=_C["primary"], font_name=T.FONT_CN,
        ))
        # Left column
        self._commands.append(AddText(
            x=0.5, y=1.3, w=4.5, h=5.8, text=left_text,
            font_size=12, color=_C["text_dark"], font_name=T.FONT_CN,
        ))
        # Right column
        self._commands.append(AddText(
            x=5.2, y=1.3, w=4.3, h=5.8, text=right_text,
            font_size=12, color=_C["text_dark"], font_name=T.FONT_NUM,
        ))

    def _add_stats_table_slide(
        self, title: str, summary_stats: dict[str, Any],
    ) -> None:
        if not summary_stats:
            return
        # Flatten grouped stats
        first_val = next(iter(summary_stats.values()))
        if isinstance(first_val, dict) and not any(
            k in first_val for k in ("mean", "median", "std", "min", "max")
        ):
            flat: dict[str, dict] = {}
            for gk, cols in summary_stats.items():
                if isinstance(cols, dict):
                    for cn, metrics in cols.items():
                        flat[f"{gk}/{cn}"] = (
                            metrics if isinstance(metrics, dict) else {}
                        )
            summary_stats = flat if flat else summary_stats

        metrics = ["mean", "median", "std", "min", "max"]
        col_names = [c for c, v in summary_stats.items() if isinstance(v, dict)]
        if not col_names:
            return

        self._commands.append(NewSlide())
        self._commands.append(AddText(
            x=0.5, y=0.3, w=9, h=0.8, text=title,
            font_size=T.SIZE_H2, bold=True,
            color=_C["primary"], font_name=T.FONT_CN,
        ))
        # Build rows
        header_row = [
            {"text": "指标", "bold": True, "fill": _C["primary"], "color": _C["white"]},
        ] + [
            {"text": metric_label(m), "bold": True,
             "fill": _C["primary"], "color": _C["white"]}
            for m in metrics
        ]
        rows: list[list[dict[str, Any]]] = [header_row]
        for col in col_names:
            vals = summary_stats[col]
            row = [{"text": col, "bold": True}]
            for m in metrics:
                v = vals.get(m)
                row.append({"text": (
                    f"{v:,.2f}" if isinstance(v, (int, float)) else "-"
                )})
            rows.append(row)

        self._commands.append(AddTable(
            x=0.5, y=1.4, w=9, h=5.5,
            rows=rows,
            options={"fontSize": 11, "fontFace": T.FONT_NUM},
        ))

    def _add_chart_table_slide(self, chart_option: dict[str, Any]) -> None:
        spec = echarts_to_pptxgen(chart_option)
        if spec is None:
            # Native chart not supported (waterfall etc.) — skip;
            # downstream Sprint 3 may render as table image.
            return

        self._commands.append(NewSlide())
        title = spec.get("title") or "数据图表"
        self._commands.append(AddText(
            x=0.5, y=0.3, w=9, h=0.7, text=title,
            font_size=T.SIZE_H2, bold=True,
            color=_C["primary"], font_name=T.FONT_CN,
        ))
        self._commands.append(AddChart(
            x=0.5, y=1.2, w=9, h=5.8,
            chart_type=spec["type"],
            data=spec["data"],
            options=spec["options"],
        ))

    def _add_kpi_cards_slide(
        self, title: str, growth_rates: dict[str, dict[str, float | None]],
    ) -> None:
        items = [
            (col, rates) for col, rates in growth_rates.items()
            if isinstance(rates, dict)
            and (rates.get("yoy") is not None or rates.get("mom") is not None)
        ]
        if not items:
            return
        items = items[:4]
        n = len(items)
        card_w = 8.0 / n
        start_x = (10 - card_w * n) / 2

        self._commands.append(NewSlide())
        self._commands.append(AddText(
            x=0.5, y=0.3, w=9, h=0.8, text=title,
            font_size=T.SIZE_H2, bold=True,
            color=_C["primary"], font_name=T.FONT_CN, alignment="center",
        ))
        for i, (col, rates) in enumerate(items):
            x = start_x + i * card_w
            self._commands.append(AddShape(
                x=x + 0.15, y=1.6, w=card_w - 0.3, h=4.5,
                shape="rect", fill=_C["bg_light"],
            ))
            self._commands.append(AddText(
                x=x + 0.3, y=1.8, w=card_w - 0.6, h=0.6, text=col,
                font_size=T.SIZE_KPI_LABEL, bold=True,
                color=_C["neutral"], font_name=T.FONT_CN,
                alignment="center",
            ))
            yoy = rates.get("yoy")
            if yoy is not None:
                arrow = "↑" if yoy >= 0 else "↓"
                color = _C["positive"] if yoy >= 0 else _C["negative"]
                self._commands.append(AddText(
                    x=x + 0.3, y=2.6, w=card_w - 0.6, h=1.2,
                    text=f"{arrow}{abs(yoy)*100:.1f}%",
                    font_size=T.SIZE_KPI_LARGE, bold=True,
                    color=color, font_name=T.FONT_NUM, alignment="center",
                ))
                self._commands.append(AddText(
                    x=x + 0.3, y=3.8, w=card_w - 0.6, h=0.5, text="同比",
                    font_size=T.SIZE_KPI_LABEL,
                    color=_C["neutral"], font_name=T.FONT_CN,
                    alignment="center",
                ))
            mom = rates.get("mom")
            if mom is not None:
                arrow = "↑" if mom >= 0 else "↓"
                color = _C["positive"] if mom >= 0 else _C["negative"]
                self._commands.append(AddText(
                    x=x + 0.3, y=4.4, w=card_w - 0.6, h=1.0,
                    text=f"{arrow}{abs(mom)*100:.1f}%",
                    font_size=24, bold=True,
                    color=color, font_name=T.FONT_NUM, alignment="center",
                ))
                self._commands.append(AddText(
                    x=x + 0.3, y=5.4, w=card_w - 0.6, h=0.5, text="环比",
                    font_size=T.SIZE_KPI_LABEL,
                    color=_C["neutral"], font_name=T.FONT_CN,
                    alignment="center",
                ))

    def _add_summary_slide(self, conclusions: list[str]) -> None:
        self._commands.append(NewSlide(background=_C["primary"]))
        self._commands.append(AddText(
            x=1, y=0.5, w=8, h=0.8, text="总结与建议",
            font_size=T.SIZE_H1, bold=True,
            color=_C["accent"], font_name=T.FONT_CN, alignment="center",
        ))
        for i, c in enumerate(conclusions[:5]):
            self._commands.append(AddText(
                x=1, y=1.6 + i * 1.0, w=8, h=0.9,
                text=f"• {c}",
                font_size=14, color=_C["white"], font_name=T.FONT_CN,
            ))

    def _add_thank_you_slide(self) -> None:
        self._commands.append(NewSlide(background=_C["primary"]))
        self._commands.append(AddText(
            x=1, y=3, w=8, h=1.5, text="谢谢观看",
            font_size=44, bold=True,
            color=_C["white"], font_name=T.FONT_CN, alignment="center",
        ))

    # ---- Section composition (mirrors PptxBlockRenderer) ------------

    def _render_section_combo(self) -> None:
        for gr in self._growth:
            self._add_kpi_cards_slide(self._current_section_name, gr)

        if self._narratives and self._stats:
            nar_text = "\n\n".join(self._narratives)
            stats_text = _stats_to_text(self._stats[0])
            self._add_two_column_slide(
                self._current_section_name, nar_text, stats_text,
            )
            for st in self._stats:
                self._add_stats_table_slide(
                    f"{self._current_section_name} - 统计数据", st,
                )
        elif self._narratives:
            self._add_narrative_slide(
                self._current_section_name,
                "\n\n".join(self._narratives),
            )
        elif self._stats:
            for st in self._stats:
                self._add_stats_table_slide(
                    f"{self._current_section_name} - 统计数据", st,
                )

        for ci in self._charts:
            self._add_chart_table_slide(ci)

    def _render_summary_and_thanks(self) -> None:
        conclusions: list[str] = [
            (t[:120] + "...") if len(t) > 120 else t
            for t in self._appendix_paragraphs
        ]
        if not conclusions:
            for nar in self._all_narratives:
                if len(nar) > 20:
                    conclusions.append(nar[:100] + "...")
                    break
        if not conclusions:
            conclusions = ["数据分析完成，详见各章节内容"]

        self._add_summary_slide(conclusions)
        self._add_thank_you_slide()

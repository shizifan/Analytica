"""PptxGenJSBlockRenderer — 辽港数据期刊 PR-4 PPTX 重设计。

SlideCommand DSL 驱动的 PPTX 渲染器。所有 slide builder 已重写为
辽港数据期刊视觉：纸色背景、16:9（13.333"×7.5"）画布、古铜强调色、
KPI strip、附录 deck、主题驱动图表颜色。

Failure handling:
- ``end_document`` may raise ``RuntimeError`` if the Node executor fails
  (missing node, executor crash, timeout). Caller (`pptx_gen.py`) must
  catch and fall back to ``PptxBlockRenderer`` (python-pptx).
"""
from __future__ import annotations

from typing import Any

from backend.tools._field_labels import col_label, metric_label
from backend.tools.report import _theme as T
from backend.tools.report._block_renderer import BlockRendererBase
from backend.tools.report._outline import (
    Asset,
    ChartBlock,
    ChartTablePairBlock,
    ComparisonGridBlock,
    GrowthIndicatorsBlock,
    KPIItem,
    KpiRowBlock,
    KpiStripBlock,
    KpiStripItem,
    OutlineSection,
    ParagraphBlock,
    ReportOutline,
    SectionCoverBlock,
    StatsAsset,
    TableAsset,
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
# Color helpers — per-instance (theme-driven in PR-4)
# ---------------------------------------------------------------------------

def _hex(rgb: tuple[int, int, int]) -> str:
    return f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


# Roman numeral lookup — used by TOC and section divider (PR-4)
_ROMAN: dict[int, str] = {
    1: "Ⅰ", 2: "Ⅱ", 3: "Ⅲ", 4: "Ⅳ", 5: "Ⅴ",
    6: "Ⅵ", 7: "Ⅶ", 8: "Ⅷ", 9: "Ⅸ", 10: "Ⅹ",
    11: "Ⅺ", 12: "Ⅻ", 13: "ⅩⅢ", 14: "ⅩⅣ", 15: "ⅩⅤ",
    16: "ⅩⅥ", 17: "ⅩⅦ", 18: "ⅩⅧ", 19: "ⅩⅨ", 20: "ⅩⅩ",
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

        # Per-instance colour lookup (theme-driven, replaces module _C)
        self._C = {
            "primary": self._theme.hex_primary,
            "secondary": self._theme.hex_secondary,
            "accent": self._theme.hex_accent,
            "positive": self._theme.hex_positive,
            "negative": self._theme.hex_negative,
            "neutral": self._theme.hex_neutral,
            "bg_light": self._theme.hex_bg_light,
            "white": self._theme.hex_white,
            "text_dark": self._theme.hex_text_dark,
        }

        # Slide canvas — used by slide builders for coordinate math
        self._slide_w = self._theme.slide_width
        self._slide_h = self._theme.slide_height

        # Appendix buffer — populated by emit_chart_table_pair,
        # flushed in end_document (PR-4: §6.7)
        self._appendix_buffer: list = []
        self._seen_appendix_assets: set[str] = set()

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
        """Flush appendix deck, serialise commands and invoke Node bridge.

        PR-4: slide dimensions flow from theme to the Node executor.
        Raises ``RuntimeError`` on any executor failure — pptx_gen.py
        catches and falls back to PptxBlockRenderer.
        """
        self._flush_appendix_deck()
        payload = serialize_commands(self._commands)
        return run_pptxgen_executor(
            payload,
            slide_width=self._slide_w,
            slide_height=self._slide_h,
        )

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
        """PR-4: 辽港 chart+KPI 页——纵向 chart 60% + KPI strip + 附录缓冲。

        图表占上方 60%，KPI strip 居中，表格推入附录缓冲。
        """
        chart_option = getattr(chart_asset, "option", None)
        if not isinstance(chart_option, dict):
            return
        spec = echarts_to_pptxgen(chart_option, theme=self._theme)
        if spec is None:
            # Unsupported chart type — emit a text placeholder slide
            title = block.title or self._current_section_name or "数据图表"
            self._commands.append(NewSlide(background=self._C["bg_light"]))
            self._commands.append(AddText(
                x=0.6, y=2.0, w=12.133, h=1.5, text=title,
                font_size=14, bold=True,
                color=self._C["primary"], font_name=T.FONT_CN,
            ))
            self._commands.append(AddText(
                x=0.6, y=3.5, w=12.133, h=1.0,
                text="此图表类型暂不支持原生渲染，详情请参见附录数据",
                font_size=11, color=self._C["neutral"], font_name=T.FONT_CN,
            ))
            return

        title = block.title or spec.get("title") or self._current_section_name or "趋势分析"
        subtitle = getattr(block, "subtitle", None) or ""

        self._commands.append(NewSlide(background=self._C["bg_light"]))
        # Figure title — 14pt navy
        self._commands.append(AddText(
            x=0.6, y=0.5, w=12.133, h=0.4, text=title,
            font_size=14, bold=True,
            color=self._C["primary"], font_name=T.FONT_CN,
        ))
        # Subtitle — 10pt ink_2
        if subtitle:
            self._commands.append(AddText(
                x=0.6, y=0.85, w=12.133, h=0.25, text=subtitle,
                font_size=10,
                color=self._C["neutral"], font_name=T.FONT_UI,
            ))
        chart_y = 0.9 if subtitle else 1.0

        # Chart — upper 60%
        self._commands.append(AddChart(
            x=0.6, y=chart_y, w=12.133, h=3.9,
            chart_type=spec["type"], data=spec["data"],
            options=spec["options"],
        ))

        # KPI strip below chart
        if block.kpi_strip:
            self._add_kpi_strip_commands(block.kpi_strip.items, y_offset=5.2)

        # Source — 9pt ink_3
        source = getattr(block, "source", None) or ""
        if source:
            self._commands.append(AddText(
                x=0.6, y=6.8, w=11.733, h=0.25,
                text=source, font_size=9,
                color=self._C["neutral"], font_name=T.FONT_UI,
            ))

        # Endmark
        self._commands.append(AddShape(
            x=12.7, y=7.0, w=0.13, h=0.13,
            shape="rect", fill=self._C["accent"],
        ))

        # Push table to appendix buffer (dedup by asset_id)
        aid = getattr(table_asset, "asset_id", id(table_asset))
        if aid not in self._seen_appendix_assets:
            self._seen_appendix_assets.add(aid)
            self._appendix_buffer.append((block, table_asset))

    # ---- KPI strip (PR-4: §6.4) ------------------------------------

    def emit_kpi_strip(self, block: KpiStripBlock) -> None:
        """PR-4: render 4-column KPI strip on the current slide."""
        self._add_kpi_strip_commands(block.items, y_offset=0)

    def _add_kpi_strip_commands(
        self, items: tuple[KpiStripItem, ...], y_offset: float,
    ) -> None:
        """Emit KPI strip commands — 2 AddShapes (hairlines) + 12 AddTexts.

        The strip spans the full content width (12.133"), divided into 4
        equal columns. Each column renders label / value / sub vertically.
        """
        if len(items) != 4:
            return

        col_w = 12.133 / 4  # ~3.033"

        # Top hairline — navy 1pt
        self._commands.append(AddShape(
            x=0.6, y=y_offset, w=12.133, h=0.012,
            shape="rect", fill=self._C["primary"],
        ))

        for i, kpi in enumerate(items):
            cx = 0.6 + i * col_w

            # Label — ui 9pt bronze (simulates smcp)
            self._commands.append(AddText(
                x=cx + 0.1, y=y_offset + 0.02, w=col_w - 0.2, h=0.25,
                text=kpi.label, font_size=9, bold=False,
                color=self._C["accent"], font_name=T.FONT_UI,
            ))

            # Value — mono 28pt, trend-driven colour
            if kpi.trend == "gain":
                vcolor = self._C["positive"]
            elif kpi.trend == "loss":
                vcolor = self._C["negative"]
            else:
                vcolor = self._C["primary"]
            self._commands.append(AddText(
                x=cx + 0.1, y=y_offset + 0.3, w=col_w - 0.2, h=0.6,
                text=kpi.value, font_size=28, bold=True,
                color=vcolor, font_name=T.FONT_NUM,
            ))

            # Sub — ui 9pt neutral
            if kpi.sub:
                self._commands.append(AddText(
                    x=cx + 0.1, y=y_offset + 1.0, w=col_w - 0.2, h=0.25,
                    text=kpi.sub, font_size=9,
                    color=self._C["neutral"], font_name=T.FONT_UI,
                ))

        # Bottom hairline — navy 1pt
        self._commands.append(AddShape(
            x=0.6, y=y_offset + 1.35, w=12.133, h=0.012,
            shape="rect", fill=self._C["primary"],
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
        self._commands.append(NewSlide(background=self._C["bg_light"]))

        # Slide title (use section name if mid-section context exists,
        # else a generic header)
        slide_title = self._current_section_name or "对比分析"
        self._commands.append(AddText(
            x=0.6, y=0.3, w=12.133, h=0.7, text=slide_title,
            font_size=T.SIZE_H2, bold=True,
            color=self._C["primary"], font_name=T.FONT_CN, alignment="left",
        ))

        n = min(len(block.columns), 4)  # cap visual at 4 columns
        margin = 0.6
        gap = 0.2
        usable = self._slide_w - 2 * margin - gap * (n - 1)
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
                shape="rounded_rect", fill=self._C["white"],
                rect_radius=0.04, shadow=True,
            ))
            # Title bar — primary-coloured strip across the top
            self._commands.append(AddShape(
                x=cx, y=col_y, w=col_w, h=title_bar_h,
                shape="rect", fill=self._C["primary"],
            ))
            # Title text
            self._commands.append(AddText(
                x=cx + 0.1, y=col_y + 0.1, w=col_w - 0.2, h=title_bar_h - 0.2,
                text=col.title, font_size=14, bold=True,
                color=self._C["white"], font_name=T.FONT_CN, alignment="center",
            ))
            # Items — bulleted list under the title bar
            items_text = "\n".join(f"• {it}" for it in col.items[:6])
            if items_text:
                self._commands.append(AddText(
                    x=cx + 0.2, y=col_y + title_bar_h + 0.15,
                    w=col_w - 0.4, h=col_h - title_bar_h - 0.3,
                    text=items_text, font_size=11,
                    color=self._C["text_dark"], font_name=T.FONT_CN,
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
        """PR-4: 辽港数据期刊封面——纸色背景 + 古铜横条 + navy 标题。"""
        self._commands.append(NewSlide(background=self._C["bg_light"]))
        # Top bronze brand bar (4" × 4pt)
        self._commands.append(AddShape(
            x=0.6, y=0.5, w=4.0, h=0.055,
            shape="rect", fill=self._C["accent"],
        ))
        # Title — display 32pt navy, left-aligned
        self._commands.append(AddText(
            x=1.5, y=2.0, w=10.333, h=1.5, text=title,
            font_size=T.SIZE_TITLE, bold=True,
            color=self._C["primary"], font_name=T.FONT_DISPLAY,
            alignment="left",
        ))
        # Deck / subtitle — 18pt ink_2
        self._commands.append(AddText(
            x=1.5, y=3.5, w=10.333, h=0.8, text=f"编制：{author}",
            font_size=18,
            color=self._C["neutral"], font_name=T.FONT_CN,
            alignment="left",
        ))
        # Metadata — 9pt bronze
        self._commands.append(AddText(
            x=1.5, y=5.5, w=10.333, h=0.5, text=date,
            font_size=9,
            color=self._C["accent"], font_name=T.FONT_UI,
            alignment="left",
        ))

    def _add_toc_slide(self, sections: list[str]) -> None:
        """PR-4: 辽港目录页——纸色 + "目  录" display 24pt navy。"""
        self._commands.append(NewSlide(background=self._C["bg_light"]))
        self._commands.append(AddText(
            x=0.6, y=0.5, w=12.133, h=0.8, text="目  录",
            font_size=24, bold=True,
            color=self._C["primary"], font_name=T.FONT_DISPLAY,
            alignment="left",
        ))
        for i, name in enumerate(sections[:10]):
            self._commands.append(AddText(
                x=1.5, y=1.5 + i * 0.5, w=10.633, h=0.45,
                text=f"{_ROMAN.get(i + 1, str(i + 1))}.  {name}",
                font_size=14, color=self._C["primary"], font_name=T.FONT_CN,
            ))

    def _add_kpi_overview_slide(self, kpis: list[KPIItem]) -> None:
        """Phase 3.5 — modernised KPI cards: rounded corners + drop
        shadow + theme-aligned accent stripe. Pre-Phase-3.5 code used
        flat ``rect`` cards on a uniform light background; new layout
        uses white cards with shadow against a slightly darker page."""
        self._commands.append(NewSlide(background=self._C["bg_light"]))
        self._commands.append(AddText(
            x=0.6, y=0.3, w=12.133, h=0.7, text="核心经营指标",
            font_size=22, bold=True,
            color=self._C["primary"], font_name=T.FONT_CN, alignment="left",
        ))
        n = min(len(kpis), 4)
        if n == 0:
            return

        # Card dimensions tuned for 1-4 KPIs filling the 13.333" canvas.
        margin = 0.6
        gap = 0.2
        usable = self._slide_w - 2 * margin - gap * (n - 1)
        card_w = usable / n
        card_radius = 0.06
        accent_stripe_h = 0.12

        for i, kpi in enumerate(kpis[:n]):
            cx = margin + i * (card_w + gap)

            if kpi.trend == "positive":
                trend_color = self._C["positive"]
            elif kpi.trend == "negative":
                trend_color = self._C["negative"]
            else:
                trend_color = self._C["accent"]

            # Card body — white rounded card with shadow
            self._commands.append(AddShape(
                x=cx, y=1.3, w=card_w - 0.2, h=4.5,
                shape="rounded_rect", fill=self._C["white"],
                rect_radius=card_radius, shadow=True,
            ))
            # Bottom accent stripe
            self._commands.append(AddShape(
                x=cx, y=1.3 + 4.5 - accent_stripe_h,
                w=card_w - 0.2, h=accent_stripe_h,
                shape="rect", fill=trend_color,
            ))
            # Label
            self._commands.append(AddText(
                x=cx + 0.1, y=1.5, w=card_w - 0.4, h=0.4,
                text=kpi.label,
                font_size=11, bold=True, color=self._C["neutral"],
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
                    color=self._C["neutral"], font_name=T.FONT_CN,
                    alignment="center",
                ))

    def _add_section_divider_slide(self, number: int, title: str) -> None:
        """PR-4: 辽港章节分隔页——纸色 + 罗马数字 + navy hairline。"""
        self._commands.append(NewSlide(background=self._C["bg_light"]))
        # Top navy hairline
        self._commands.append(AddShape(
            x=0.6, y=0.6, w=12.133, h=0.012,
            shape="rect", fill=self._C["primary"],
        ))
        # Large Roman numeral — display 120pt bronze
        roman = _ROMAN.get(number, str(number))
        self._commands.append(AddText(
            x=0.6, y=2.0, w=4.0, h=3.5, text=roman,
            font_size=120, bold=False,
            color=self._C["accent"], font_name=T.FONT_DISPLAY,
        ))
        # Section title — 28pt navy
        self._commands.append(AddText(
            x=5.5, y=3.0, w=7.0, h=2.0, text=title,
            font_size=T.SIZE_H1, bold=True,
            color=self._C["primary"], font_name=T.FONT_DISPLAY,
        ))
        # Endmark — bronze square, bottom-right
        self._commands.append(AddShape(
            x=12.7, y=7.0, w=0.13, h=0.13,
            shape="rect", fill=self._C["accent"],
        ))

    def _add_narrative_slide(self, title: str, text: str) -> None:
        """PR-4: 辽港叙述页——kicker + 左侧古铜竖条 + lede + body。"""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        chunk_size = 12
        chunks = [lines[i:i + chunk_size] for i in range(0, len(lines), chunk_size)]
        if not chunks:
            chunks = [["（暂无详细内容）"]]
        for ci, chunk in enumerate(chunks):
            self._commands.append(NewSlide(background=self._C["bg_light"]))
            # Kicker — section name, ui 8pt bronze
            self._commands.append(AddText(
                x=0.6, y=0.5, w=12.133, h=0.3,
                text=title,
                font_size=8, bold=False,
                color=self._C["accent"], font_name=T.FONT_UI,
            ))
            # Left bronze brand bar — 4×80pt
            self._commands.append(AddShape(
                x=0.6, y=1.0, w=0.055, h=1.11,
                shape="rect", fill=self._C["accent"],
            ))
            # Lede — first line, display 18pt ink_2
            lede_text = chunk[0] if chunk else "（暂无详细内容）"
            self._commands.append(AddText(
                x=0.9, y=1.0, w=11.4, h=0.8,
                text=lede_text[:120],
                font_size=18, bold=False,
                color=self._C["neutral"], font_name=T.FONT_DISPLAY,
            ))
            # Body — rest, 11pt ink_1
            body_text = "\n".join(chunk[1:]) if len(chunk) > 1 else ""
            if body_text:
                self._commands.append(AddText(
                    x=0.9, y=2.0, w=11.4, h=4.8,
                    text=body_text,
                    font_size=11, bold=False,
                    color=self._C["text_dark"], font_name=T.FONT_CN,
                ))

    def _add_two_column_slide(
        self, title: str, left_text: str, right_text: str,
    ) -> None:
        self._commands.append(NewSlide(background=self._C["bg_light"]))
        self._commands.append(AddText(
            x=0.6, y=0.3, w=12.133, h=0.8, text=title,
            font_size=T.SIZE_H2, bold=True,
            color=self._C["primary"], font_name=T.FONT_CN,
        ))
        # Left column
        self._commands.append(AddText(
            x=0.6, y=1.3, w=6.0, h=5.8, text=left_text,
            font_size=12, color=self._C["text_dark"], font_name=T.FONT_CN,
        ))
        # Right column
        self._commands.append(AddText(
            x=6.9, y=1.3, w=5.8, h=5.8, text=right_text,
            font_size=12, color=self._C["text_dark"], font_name=T.FONT_NUM,
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

        self._commands.append(NewSlide(background=self._C["bg_light"]))
        self._commands.append(AddText(
            x=0.6, y=0.3, w=12.133, h=0.8, text=title,
            font_size=T.SIZE_H2, bold=True,
            color=self._C["primary"], font_name=T.FONT_CN,
        ))
        # Build rows
        header_row = [
            {"text": "指标", "bold": True, "fill": self._C["primary"], "color": self._C["white"]},
        ] + [
            {"text": metric_label(m), "bold": True,
             "fill": self._C["primary"], "color": self._C["white"]}
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
            x=0.6, y=1.4, w=12.133, h=5.5,
            rows=rows,
            options={"fontSize": 11, "fontFace": T.FONT_NUM},
        ))

    def _add_chart_narrative_slide(
        self, chart_option: dict[str, Any], narrative: str = "",
    ) -> None:
        """Compact slide: chart (upper 55%) + narrative text (lower region).
        Avoids fragmenting one section’s analysis across three separate slides.
        """
        spec = echarts_to_pptxgen(chart_option, theme=self._theme)
        if spec is None:
            title = chart_option.get("title", {}).get("text") or "数据图表"
            self._commands.append(NewSlide(background=self._C["bg_light"]))
            self._commands.append(AddText(
                x=0.6, y=2.0, w=12.133, h=1.5, text=title,
                font_size=14, bold=True,
                color=self._C["primary"], font_name=T.FONT_CN,
            ))
            return

        self._commands.append(NewSlide(background=self._C["bg_light"]))
        title = spec.get("title") or "数据图表"
        self._commands.append(AddText(
            x=0.6, y=0.3, w=12.133, h=0.35, text=title,
            font_size=13, bold=True,
            color=self._C["primary"], font_name=T.FONT_CN,
        ))
        # Chart — upper 55%
        self._commands.append(AddChart(
            x=0.6, y=0.75, w=12.133, h=3.6,
            chart_type=spec["type"],
            data=spec["data"],
            options=spec["options"],
        ))
        # Narrative text below chart
        if narrative:
            self._commands.append(AddText(
                x=0.6, y=4.5, w=12.133, h=2.8, text=narrative,
                font_size=12, color=self._C["text_dark"], font_name=T.FONT_CN,
            ))

    def _add_chart_table_slide(self, chart_option: dict[str, Any]) -> None:
        """PR-4: 辽港图表页——图题 + chart 70% + endmark。
        不支持的类型改为文本占位符，不降级为 PNG fallback。
        """
        spec = echarts_to_pptxgen(chart_option, theme=self._theme)
        if spec is None:
            # Unsupported chart type — emit a text placeholder slide
            title = chart_option.get("title", {}).get("text") or "数据图表"
            self._commands.append(NewSlide(background=self._C["bg_light"]))
            self._commands.append(AddText(
                x=0.6, y=2.0, w=12.133, h=1.5, text=title,
                font_size=14, bold=True,
                color=self._C["primary"], font_name=T.FONT_CN,
            ))
            self._commands.append(AddText(
                x=0.6, y=3.5, w=12.133, h=1.0,
                text="此图表类型暂不支持原生渲染，详情请参见附录数据",
                font_size=11, color=self._C["neutral"], font_name=T.FONT_CN,
            ))
            return

        self._commands.append(NewSlide(background=self._C["bg_light"]))
        # Figure title — 14pt navy
        title = spec.get("title") or "数据图表"
        self._commands.append(AddText(
            x=0.6, y=0.5, w=12.133, h=0.4, text=title,
            font_size=14, bold=True,
            color=self._C["primary"], font_name=T.FONT_CN,
        ))
        # Chart — 70% of content height
        self._commands.append(AddChart(
            x=0.6, y=1.0, w=12.133, h=4.8,
            chart_type=spec["type"],
            data=spec["data"],
            options=spec["options"],
        ))
        # Endmark — bronze square, bottom-right
        self._commands.append(AddShape(
            x=12.7, y=7.0, w=0.13, h=0.13,
            shape="rect", fill=self._C["accent"],
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
        margin = 0.6
        gap = 0.2
        usable = self._slide_w - 2 * margin - gap * (n - 1)
        card_w = usable / n
        start_x = margin

        self._commands.append(NewSlide(background=self._C["bg_light"]))
        self._commands.append(AddText(
            x=0.6, y=0.3, w=12.133, h=0.8, text=title,
            font_size=T.SIZE_H2, bold=True,
            color=self._C["primary"], font_name=T.FONT_CN, alignment="center",
        ))
        for i, (col, rates) in enumerate(items):
            x = start_x + i * (card_w + gap)
            self._commands.append(AddShape(
                x=x + 0.15, y=1.6, w=card_w - 0.3, h=4.5,
                shape="rect", fill=self._C["bg_light"],
            ))
            self._commands.append(AddText(
                x=x + 0.3, y=1.8, w=card_w - 0.6, h=0.6, text=col_label(col),
                font_size=T.SIZE_KPI_LABEL, bold=True,
                color=self._C["neutral"], font_name=T.FONT_CN,
                alignment="center",
            ))
            yoy = rates.get("yoy")
            if yoy is not None:
                arrow = "↑" if yoy >= 0 else "↓"
                color = self._C["positive"] if yoy >= 0 else self._C["negative"]
                self._commands.append(AddText(
                    x=x + 0.3, y=2.6, w=card_w - 0.6, h=1.2,
                    text=f"{arrow}{abs(yoy)*100:.1f}%",
                    font_size=T.SIZE_KPI_LARGE, bold=True,
                    color=color, font_name=T.FONT_NUM, alignment="center",
                ))
                self._commands.append(AddText(
                    x=x + 0.3, y=3.8, w=card_w - 0.6, h=0.5, text="同比",
                    font_size=T.SIZE_KPI_LABEL,
                    color=self._C["neutral"], font_name=T.FONT_CN,
                    alignment="center",
                ))
            mom = rates.get("mom")
            if mom is not None:
                arrow = "↑" if mom >= 0 else "↓"
                color = self._C["positive"] if mom >= 0 else self._C["negative"]
                self._commands.append(AddText(
                    x=x + 0.3, y=4.4, w=card_w - 0.6, h=1.0,
                    text=f"{arrow}{abs(mom)*100:.1f}%",
                    font_size=24, bold=True,
                    color=color, font_name=T.FONT_NUM, alignment="center",
                ))
                self._commands.append(AddText(
                    x=x + 0.3, y=5.4, w=card_w - 0.6, h=0.5, text="环比",
                    font_size=T.SIZE_KPI_LABEL,
                    color=self._C["neutral"], font_name=T.FONT_CN,
                    alignment="center",
                ))

    def _add_summary_slide(self, conclusions: list[str]) -> None:
        """PR-4: 辽港总结页——纸色背景。"""
        self._commands.append(NewSlide(background=self._C["bg_light"]))
        self._commands.append(AddText(
            x=1.5, y=1.0, w=10.333, h=0.8, text="总结",
            font_size=T.SIZE_H1, bold=True,
            color=self._C["primary"], font_name=T.FONT_DISPLAY, alignment="left",
        ))
        for i, c in enumerate(conclusions[:5]):
            self._commands.append(AddText(
                x=1.5, y=2.0 + i * 0.9, w=10.333, h=0.8,
                text=f"• {c}",
                font_size=14, color=self._C["text_dark"], font_name=T.FONT_CN,
            ))

    def _add_closing_slide(self) -> None:
        """PR-4: 辽港结语页——纸色 + 居中结语 + 古铜 endmark。"""
        self._commands.append(NewSlide(background=self._C["bg_light"]))
        self._commands.append(AddText(
            x=3.0, y=2.5, w=7.333, h=1.5, text="结语",
            font_size=32, bold=True,
            color=self._C["primary"], font_name=T.FONT_DISPLAY, alignment="center",
        ))
        # Centered bronze endmark square
        self._commands.append(AddShape(
            x=6.5, y=4.5, w=0.333, h=0.333,
            shape="rect", fill=self._C["accent"],
        ))

    # ---- Appendix deck (PR-4: §6.7) -------------------------------

    def _flush_appendix_deck(self) -> None:
        """Flush the appendix buffer at end of document.

        Emits appendix cover slide + paginated detail slides for each
        buffered table asset.
        """
        if not self._appendix_buffer:
            self._add_closing_slide()
            return

        self._add_appendix_cover_slide()
        for block, asset in self._appendix_buffer:
            self._add_appendix_detail_slides(block, asset)
        self._add_closing_slide()

    def _add_appendix_cover_slide(self) -> None:
        """PR-4: 附录封面——古铜背景 + 纸色大字。"""
        self._commands.append(NewSlide(background=self._C["accent"]))
        self._commands.append(AddText(
            x=0.6, y=2.0, w=12.133, h=2.0, text="附录",
            font_size=72, bold=True,
            color=self._C["bg_light"], font_name=T.FONT_DISPLAY,
        ))
        self._commands.append(AddText(
            x=0.6, y=4.5, w=12.133, h=1.0, text="完整数据明细",
            font_size=24,
            color=self._C["bg_light"], font_name=T.FONT_CN,
        ))

    def _add_appendix_detail_slides(
        self, block, asset: Asset,
    ) -> None:
        """PR-4: 附录数据表——纸色背景 + agate 表格，每页 ≤15 行。"""
        if not isinstance(asset, TableAsset):
            return

        import pandas as pd
        df = (
            pd.DataFrame.from_records(asset.df_records)
            if asset.df_records
            else pd.DataFrame()
        )
        if df.empty:
            return

        caption = getattr(block, "title", None) or "完整数据"
        max_rows = 15
        total_pages = (len(df) + max_rows - 1) // max_rows

        for page in range(total_pages):
            start = page * max_rows
            end = min(start + max_rows, len(df))
            chunk = df.iloc[start:end]

            self._commands.append(NewSlide(background=self._C["bg_light"]))
            page_suffix = f" ({page + 1}/{total_pages})" if total_pages > 1 else ""
            self._commands.append(AddText(
                x=0.6, y=0.5, w=12.133, h=0.4,
                text=f"{caption}{page_suffix}",
                font_size=12, bold=True,
                color=self._C["primary"], font_name=T.FONT_CN,
            ))

            # Build table rows
            cols = [str(c) for c in df.columns]
            header_row = [
                {"text": c, "bold": True,
                 "fill": self._C["primary"], "color": self._C["bg_light"]}
                for c in cols
            ]
            rows: list[list[dict[str, Any]]] = [header_row]
            for _, row_data in chunk.iterrows():
                row = []
                for i, col in enumerate(cols):
                    val = row_data[col]
                    if isinstance(val, float):
                        text = f"{val:,.2f}"
                    else:
                        text = str(val)
                    row.append({"text": text})
                rows.append(row)

            self._commands.append(AddTable(
                x=0.6, y=1.0, w=12.133, h=5.5,
                rows=rows,
                options={"fontSize": 9, "fontFace": T.FONT_UI},
            ))

    # ---- Section composition (mirrors PptxBlockRenderer) ------------

    def _render_section_combo(self) -> None:
        """Emit a compact layout: chart(s) + leading narrative on one
        slide, growth cards on a compact slide, stats to appendix."""
        nar_text = "\n\n".join(self._narratives) if self._narratives else ""

        # Chart + short narrative on one slide
        if self._charts:
            short_nar = nar_text[:180] + "…" if len(nar_text) > 180 else nar_text
            self._add_chart_narrative_slide(
                chart_option=self._charts[0], narrative=short_nar,
            )
            for ci in self._charts[1:]:
                self._add_chart_table_slide(ci)
        elif nar_text:
            self._add_narrative_slide(self._current_section_name, nar_text)

        # Growth cards — compact standalone
        for gr in self._growth:
            self._add_kpi_cards_slide(self._current_section_name, gr)

        # Stats → appendix
        for st in self._stats:
            self._add_stats_table_slide(
                f"{self._current_section_name} - 统计数据", st,
            )

    def _render_summary_and_thanks(self) -> None:
        """PR-4: summary/closing are now handled by _flush_appendix_deck."""
        pass

"""DOCX BlockRenderer — Step 4.

Output is structurally equivalent to the previous
``_build_docx_deterministic`` path (guarded by
``tests/contract/test_report_outputs_baseline.py``). Implementation
wraps the existing ``_docx_elements`` builders; the original heading
text written by each builder is preserved (block ``caption`` fields are
ignored by DOCX since the builders own their headings — by design,
matching pre-refactor output).
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd
from docx import Document

from backend.tools.report import _docx_elements as E
from backend.tools.report._block_renderer import BlockRendererBase
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
    TableAsset,
    TableBlock,
)


@dataclass
class _AppendixItem:
    """Duck-typed substitute for ``SummaryTextItem`` used by
    ``E.build_summary_section`` — the function only reads ``.text``."""

    text: str


class DocxBlockRenderer(BlockRendererBase):
    _step_label = "Step 4"

    def __init__(self, theme=None) -> None:  # noqa: ANN001
        super().__init__(theme=theme)
        self._doc = Document()
        self._title: str = ""
        self._current_role: str = "status"
        self._appendix_buffer: list[_AppendixItem] = []

    # ---- Lifecycle -----------------------------------------------------

    def begin_document(self, outline: ReportOutline) -> None:
        self._title = outline.metadata.get("title", "")
        author = outline.metadata.get("author", "")
        date = outline.metadata.get("date", "")

        E.build_styles(self._doc)
        E.build_page_header_footer(self._doc, self._title)
        E.build_cover_page(self._doc, self._title, author, date)
        E.build_toc_placeholder(self._doc)
        if outline.kpi_summary:
            E.build_kpi_row(self._doc, list(outline.kpi_summary))

    def end_document(self) -> bytes:
        buffer = io.BytesIO()
        self._doc.save(buffer)
        return buffer.getvalue()

    def begin_section(self, section: OutlineSection, index: int) -> None:
        self._current_role = section.role
        if section.role == "appendix":
            # build_summary_section adds its own H1 ("总结与建议") and
            # default sentence on empty input — buffer paragraphs and
            # render in end_section.
            self._appendix_buffer = []
        # Phase 3.1: non-appendix sections delegate the H1 heading to
        # ``emit_section_cover`` (driven by the SectionCoverBlock that
        # legacy converter / LLM planner inserts as the section's first
        # block). begin_section is now state-only.

    def end_section(self, section: OutlineSection, index: int) -> None:
        if section.role == "appendix":
            E.build_summary_section(self._doc, list(self._appendix_buffer))

    # ---- Block emitters ------------------------------------------------

    def emit_kpi_row(self, block: KpiRowBlock) -> None:
        if block.items:
            E.build_kpi_row(self._doc, list(block.items))

    def emit_paragraph(self, block: ParagraphBlock) -> None:
        # Phase 4.1 — callout styles render with left border + tinted bg
        # via build_callout; appendix paragraphs ignore callout style
        # since the appendix renders as bullets via build_summary_section.
        if (
            self._current_role != "appendix"
            and block.style in ("callout-warn", "callout-info")
        ):
            level = "warn" if block.style == "callout-warn" else "info"
            E.build_callout(self._doc, block.text, level=level, theme=self._theme)
            return

        if self._current_role == "appendix":
            self._appendix_buffer.append(_AppendixItem(text=block.text))
        else:
            E.build_narrative(self._doc, block.text)

    def emit_table(self, block: TableBlock, asset: Asset) -> None:
        if isinstance(asset, StatsAsset):
            E.build_stats_table(self._doc, asset.summary_stats)
        elif isinstance(asset, TableAsset):
            df = (
                pd.DataFrame.from_records(asset.df_records)
                if asset.df_records
                else pd.DataFrame()
            )
            heading = block.caption or "数据明细"
            E.build_dataframe_table(
                self._doc, df,
                highlight_rules=block.highlight_rules,
                theme=self._theme,
                heading=heading,
            )

    def emit_chart(self, block: ChartBlock, asset: Asset) -> None:
        """Render a chart by embedding a matplotlib PNG when possible;
        fall back to an OOXML data table when the chart type isn't
        natively representable (waterfall, scatter, …) or when the
        renderer raises.
        """
        option = getattr(asset, "option", None)
        if not isinstance(option, dict):
            return

        # Phase 2.2 — try native picture first
        try:
            from backend.tools.report._chart_renderer import render_chart_to_png

            png_bytes = render_chart_to_png(option, self._theme)
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("analytica.tools.report.docx").warning(
                "matplotlib render failed (%s); falling back to data table", e,
            )
            png_bytes = None

        if png_bytes:
            from docx.shared import Inches

            # Title (drawn from chart option, keeps the heading style aligned
            # with the data-table fallback's add_heading('图表数据') call).
            title = ""
            title_obj = option.get("title")
            if isinstance(title_obj, dict):
                title = title_obj.get("text", "")
            elif isinstance(title_obj, str):
                title = title_obj
            if title:
                self._doc.add_heading(title, level=2)

            self._doc.add_picture(io.BytesIO(png_bytes), width=Inches(6.0))
            self._doc.add_paragraph("")  # bottom spacing
            return

        # Fallback: data table (pre-Phase-2 behaviour)
        E.build_chart_data_table(self._doc, option)

    def emit_chart_table_pair(
        self,
        block: ChartTablePairBlock,
        chart_asset: Asset,
        table_asset: Asset,
    ) -> None:
        synth_chart = ChartBlock(
            block_id=block.block_id,
            asset_id=block.chart_asset_id,
        )
        synth_table = TableBlock(
            block_id=block.block_id,
            asset_id=block.table_asset_id,
        )
        self.emit_chart(synth_chart, chart_asset)
        self.emit_table(synth_table, table_asset)

    def emit_comparison_grid(self, block: ComparisonGridBlock) -> None:
        """Phase 3.2 — N-column comparison grid with primary-coloured
        title row and bulleted item cells. Used by the LLM planner /
        legacy converter on ``role="recommendation"`` sections (e.g.
        短期 / 中期 / 长期)."""
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.shared import Pt

        if not block.columns:
            return
        n_cols = len(block.columns)
        max_items = max(len(c.items) for c in block.columns)
        if max_items == 0:
            return

        table = self._doc.add_table(rows=1 + max_items, cols=n_cols)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = "Table Grid"

        # Title row — primary background + white bold text
        for ci, col in enumerate(block.columns):
            cell = table.rows[0].cells[ci]
            cell.text = col.title
            E._set_cell_shading(cell, self._theme.hex_primary)
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.bold = True
                    run.font.size = Pt(self._theme.size_table_header)
                    from docx.shared import RGBColor
                    run.font.color.rgb = RGBColor(*self._theme.white)

        # Item rows — bulleted, theme body size
        for ci, col in enumerate(block.columns):
            for ri, item in enumerate(col.items):
                cell = table.rows[1 + ri].cells[ci]
                cell.text = f"• {item}"
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.font.size = Pt(self._theme.size_body)
        self._doc.add_paragraph("")  # bottom spacing

    def emit_growth_indicators(self, block: GrowthIndicatorsBlock) -> None:
        if block.growth_rates:
            E.build_growth_indicators(self._doc, block.growth_rates)

    def emit_section_cover(self, block: SectionCoverBlock) -> None:
        """Render the section's heading. DOCX uses the existing H1
        builder — section dividers stay visually equivalent to the
        pre-Phase-3.1 output. Future refinements (page-break +
        full-bleed coloured strip) live in this method.
        """
        E.build_section_heading(self._doc, block.index, block.title)

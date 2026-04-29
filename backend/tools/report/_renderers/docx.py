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

    def __init__(self) -> None:
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
        else:
            E.build_section_heading(self._doc, 0, section.name)

    def end_section(self, section: OutlineSection, index: int) -> None:
        if section.role == "appendix":
            E.build_summary_section(self._doc, list(self._appendix_buffer))

    # ---- Block emitters ------------------------------------------------

    def emit_kpi_row(self, block: KpiRowBlock) -> None:
        if block.items:
            E.build_kpi_row(self._doc, list(block.items))

    def emit_paragraph(self, block: ParagraphBlock) -> None:
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
            E.build_dataframe_table(self._doc, df)

    def emit_chart(self, block: ChartBlock, asset: Asset) -> None:
        # ChartAsset has .option; degrade gracefully on any other asset.
        option = getattr(asset, "option", None)
        if isinstance(option, dict):
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
        # Legacy converter never emits this; render as N-column table.
        # Visual polish (column shading, borders) is Sprint-3 work.
        from docx.enum.table import WD_TABLE_ALIGNMENT

        if not block.columns:
            return
        n_cols = len(block.columns)
        max_items = max(len(c.items) for c in block.columns)
        table = self._doc.add_table(rows=1 + max_items, cols=n_cols)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = "Table Grid"
        for ci, col in enumerate(block.columns):
            table.rows[0].cells[ci].text = col.title
            for ri, item in enumerate(col.items):
                table.rows[1 + ri].cells[ci].text = item

    def emit_growth_indicators(self, block: GrowthIndicatorsBlock) -> None:
        if block.growth_rates:
            E.build_growth_indicators(self._doc, block.growth_rates)

    def emit_section_cover(self, block: SectionCoverBlock) -> None:
        # Lightweight placeholder until Sprint 3 deep-cover styling lands.
        E.build_section_heading(self._doc, block.index, block.title)

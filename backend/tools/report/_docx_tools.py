"""DOCX outline-driven LLM agent tools — Step 4.

The agent's job under the outline pipeline is *to render* (not plan):
the outline already describes what each section contains, and each tool
calls the matching ``DocxBlockRenderer.emit_*`` method given a block_id.
This is a much smaller decision space than the pre-refactor agent (which
had to pick from 7+ heterogeneous content types and manage section
ordering itself), so success rate goes up and the system prompt shrinks.

Usage::

    renderer = DocxBlockRenderer()
    tools = make_docx_outline_tools(renderer, outline)
    success = await run_report_agent(
        llm, tools, DOCX_OUTLINE_SYSTEM_PROMPT,
        serialize_outline(outline),
    )
    if success:
        docx_bytes = renderer.end_document()
"""
from __future__ import annotations

from langchain_core.tools import tool

from backend.tools.report._agent_loop import FINALIZE_SENTINEL
from backend.tools.report._outline import (
    ChartBlock,
    ChartTablePairBlock,
    ComparisonGridBlock,
    GrowthIndicatorsBlock,
    KpiRowBlock,
    ParagraphBlock,
    ReportOutline,
    SectionCoverBlock,
    TableBlock,
)
from backend.tools.report._renderers.docx import DocxBlockRenderer


DOCX_OUTLINE_SYSTEM_PROMPT = """\
你是 Word 文档渲染执行者。报告大纲(outline)已经规划完毕——你的任务是按 outline 的顺序，
逐个调用工具把每个 block 渲染到文档中。

## 工作流程
1. 调用 begin_document
2. 对每个 Section（按编号 0, 1, 2, ... 顺序）:
   a. 调用 begin_section(section_index)
   b. 按用户消息中给出的顺序, 对每个 block 调用对应的 emit_* 工具(传入 block_id)
   c. 调用 end_section(section_index)
3. 调用 finalize_document

## Block 与工具对应
- kpi_row → emit_kpi_row(block_id)
- paragraph → emit_paragraph(block_id)
- table → emit_table(block_id)
- chart → emit_chart(block_id)
- chart_table_pair → emit_chart_table_pair(block_id)
- comparison_grid → emit_comparison_grid(block_id)
- growth_indicators → emit_growth_indicators(block_id)
- section_cover → emit_section_cover(block_id)

## 重要规则
- block_id 必须严格使用 outline 中提供的字符串 ID(如 "B0007"), 不要编造
- 调用工具时不要补章节编号("一、" 等已经在 section 名字里), section_index 是 0-based 整数
- 空 section(无 block)只需调用 begin_section / end_section, 不要 emit
- 完成后必须调用 finalize_document
"""


def make_docx_outline_tools(
    renderer: DocxBlockRenderer,
    outline: ReportOutline,
) -> list:
    """Return a list of LangChain tools that drive *renderer* via *outline*."""

    def _section(idx: int):
        if idx < 0 or idx >= len(outline.sections):
            raise IndexError(
                f"section_index={idx} 越界 (0-{len(outline.sections)-1})"
            )
        return outline.sections[idx]

    def _block(block_id: str, expected_type: type):
        block = outline.find_block(block_id)
        if block is None:
            raise KeyError(f"block_id {block_id!r} 不存在于 outline")
        if not isinstance(block, expected_type):
            raise TypeError(
                f"block {block_id!r} 是 {type(block).__name__}, "
                f"期望 {expected_type.__name__}"
            )
        return block

    # ---- Lifecycle ------------------------------------------------------

    @tool
    def begin_document() -> str:
        """Initialise the document (cover, TOC, global KPI). Call once first."""
        renderer.begin_document(outline)
        return "✓ document started"

    @tool
    def begin_section(section_index: int) -> str:
        """Start a section. ``section_index`` is 0-based."""
        section = _section(section_index)
        renderer.begin_section(section, section_index)
        return f"✓ section {section_index} (\"{section.name}\") begun"

    @tool
    def end_section(section_index: int) -> str:
        """End a section. ``section_index`` matches the prior begin_section."""
        section = _section(section_index)
        renderer.end_section(section, section_index)
        return f"✓ section {section_index} ended"

    @tool
    def finalize_document() -> str:
        """Mark rendering complete. Must be called last; ends the agent loop."""
        return FINALIZE_SENTINEL

    # ---- Block emitters -------------------------------------------------

    @tool
    def emit_kpi_row(block_id: str) -> str:
        """Render a KPI row block."""
        block = _block(block_id, KpiRowBlock)
        renderer.emit_kpi_row(block)
        return f"✓ kpi_row {block_id}"

    @tool
    def emit_paragraph(block_id: str) -> str:
        """Render a narrative paragraph."""
        block = _block(block_id, ParagraphBlock)
        renderer.emit_paragraph(block)
        return f"✓ paragraph {block_id}"

    @tool
    def emit_table(block_id: str) -> str:
        """Render a stats table or dataframe table."""
        block = _block(block_id, TableBlock)
        asset = outline.get_asset(block.asset_id)
        renderer.emit_table(block, asset)
        return f"✓ table {block_id} (asset={block.asset_id})"

    @tool
    def emit_chart(block_id: str) -> str:
        """Render a chart-as-data-table block."""
        block = _block(block_id, ChartBlock)
        asset = outline.get_asset(block.asset_id)
        renderer.emit_chart(block, asset)
        return f"✓ chart {block_id} (asset={block.asset_id})"

    @tool
    def emit_chart_table_pair(block_id: str) -> str:
        """Render a chart + table side-by-side block."""
        block = _block(block_id, ChartTablePairBlock)
        chart_asset = outline.get_asset(block.chart_asset_id)
        table_asset = outline.get_asset(block.table_asset_id)
        renderer.emit_chart_table_pair(block, chart_asset, table_asset)
        return f"✓ chart_table_pair {block_id}"

    @tool
    def emit_comparison_grid(block_id: str) -> str:
        """Render a multi-column comparison grid (e.g. 短期/中期/长期)."""
        block = _block(block_id, ComparisonGridBlock)
        renderer.emit_comparison_grid(block)
        return f"✓ comparison_grid {block_id}"

    @tool
    def emit_growth_indicators(block_id: str) -> str:
        """Render growth-rate indicators (yoy / mom)."""
        block = _block(block_id, GrowthIndicatorsBlock)
        renderer.emit_growth_indicators(block)
        return f"✓ growth_indicators {block_id}"

    @tool
    def emit_section_cover(block_id: str) -> str:
        """Render a section cover (placeholder until Sprint 3)."""
        block = _block(block_id, SectionCoverBlock)
        renderer.emit_section_cover(block)
        return f"✓ section_cover {block_id}"

    return [
        begin_document,
        begin_section,
        end_section,
        finalize_document,
        emit_kpi_row,
        emit_paragraph,
        emit_table,
        emit_chart,
        emit_chart_table_pair,
        emit_comparison_grid,
        emit_growth_indicators,
        emit_section_cover,
    ]

"""DOCX tool factory — wraps _docx_elements builder functions as LangChain tools.

Usage inside ``DocxReportSkill.execute()``::

    tools = make_docx_tools(doc, content)
    success = await run_report_agent(llm, tools, DOCX_SYSTEM_PROMPT, msg)
"""
from __future__ import annotations

from typing import Any

from docx import Document
from langchain_core.tools import tool

from backend.skills.report import _docx_elements as E
from backend.skills.report._agent_loop import FINALIZE_SENTINEL
from backend.skills.report._content_collector import (
    ChartDataItem,
    DataFrameItem,
    GrowthItem,
    NarrativeItem,
    ReportContent,
    StatsTableItem,
)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

DOCX_SYSTEM_PROMPT = """\
你是一位专业的数据分析报告排版师。你的任务是使用提供的工具将分析内容组合成一份结构完整、排版专业的 Word 文档。

## 排版规范
1. 首先添加封面页（add_cover_page），然后添加目录（add_toc）
2. 如果存在 KPI 指标（用户消息中会标注 "KPI 卡片: N 张"），在目录之后调用 add_kpi_cards
3. 按章节顺序处理每个 Section：先添加章节标题（add_section_heading，只传 title），再添加该章节的所有内容项
4. 章节内建议的内容顺序：叙述文本 → 统计表格 → 增长率指标 → 图表数据表 → 数据明细表
5. 最后添加总结章节（add_summary_section）
6. 完成后必须调用 finalize_document

## 重要规则
- 通过 section_index 和 item_index 引用内容，对应用户消息中的 Section 编号和 [] 编号
- 章节名通常已带中文数字前缀（"一、经营摘要"），调用 add_section_heading 只传 title 即可，不要再加 "1." 这类编号
- 不要跳过有内容的章节
- 不要自行编造数据
- 空章节可以跳过
- 如果某个 Section 没有特定类型的内容项，不要尝试添加
"""


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def make_docx_tools(doc: Document, content: ReportContent) -> list:
    """Return LangChain tools that operate on *doc* via closure."""

    def _lookup(section_index: int, item_index: int, expected_type: type) -> Any:
        """Validate indices and return the content item, or raise."""
        if section_index < 0 or section_index >= len(content.sections):
            raise IndexError(
                f"section_index={section_index} 越界 (0-{len(content.sections)-1})"
            )
        sec = content.sections[section_index]
        if item_index < 0 or item_index >= len(sec.items):
            raise IndexError(
                f"item_index={item_index} 越界，Section '{sec.name}' 共 {len(sec.items)} 项"
            )
        item = sec.items[item_index]
        if not isinstance(item, expected_type):
            raise TypeError(
                f"Section[{section_index}][{item_index}] 是 {type(item).__name__}，"
                f"期望 {expected_type.__name__}"
            )
        return item

    # ── Tools ──────────────────────────────────────────────────────

    @tool
    def add_cover_page(title: str, author: str, date: str) -> str:
        """添加报告封面页，包含标题、作者和日期。"""
        E.build_cover_page(doc, title, author, date)
        return f"✓ 封面页已添加：{title}"

    @tool
    def add_toc() -> str:
        """添加目录占位符（可在 Word 中刷新生成目录）。"""
        E.build_toc_placeholder(doc)
        return "✓ 目录已添加"

    @tool
    def add_section_heading(title: str, number: int | None = None) -> str:
        """添加章节标题。``number`` 参数保留兼容旧调用，但渲染时忽略——
        模板的章节名通常已带 "一、/二、" 等中文编号，不要再叠加阿拉伯数字。
        """
        E.build_section_heading(doc, number or 0, title)
        return f"✓ 章节标题已添加：{title}"

    @tool
    def add_kpi_cards() -> str:
        """在报告顶部添加业务 KPI 卡片行（封面/目录之后，章节之前）。

        使用内置的 ReportContent.kpi_cards 数据，无需参数。
        """
        if not content.kpi_cards:
            return "（无 KPI 可渲染，跳过）"
        E.build_kpi_row(doc, content.kpi_cards)
        return f"✓ KPI 卡片已添加（{len(content.kpi_cards)} 张）"

    @tool
    def add_narrative(section_index: int, item_index: int) -> str:
        """添加叙述分析文本段落。通过 section_index 和 item_index 指定内容。"""
        item = _lookup(section_index, item_index, NarrativeItem)
        E.build_narrative(doc, item.text)
        return f"✓ 叙述文本已添加（{len(item.text)} 字符）"

    @tool
    def add_stats_table(section_index: int, item_index: int) -> str:
        """添加统计数据汇总表格（含 mean/median/std/min/max）。"""
        item = _lookup(section_index, item_index, StatsTableItem)
        E.build_stats_table(doc, item.summary_stats)
        return f"✓ 统计表格已添加（{len(item.summary_stats)} 列）"

    @tool
    def add_growth_indicators(section_index: int, item_index: int) -> str:
        """添加增长率指标（同比/环比箭头）。"""
        item = _lookup(section_index, item_index, GrowthItem)
        E.build_growth_indicators(doc, item.growth_rates)
        return f"✓ 增长率指标已添加（{len(item.growth_rates)} 项）"

    @tool
    def add_dataframe_table(section_index: int, item_index: int) -> str:
        """添加原始数据明细表格（DataFrame）。"""
        item = _lookup(section_index, item_index, DataFrameItem)
        E.build_dataframe_table(doc, item.df)
        return f"✓ 数据明细表已添加（{item.df.shape[0]} 行 × {item.df.shape[1]} 列）"

    @tool
    def add_chart_data_table(section_index: int, item_index: int) -> str:
        """添加图表数据表格（从 ECharts 配置提取数据）。"""
        item = _lookup(section_index, item_index, ChartDataItem)
        E.build_chart_data_table(doc, item.option)
        return f"✓ 图表数据表已添加：{item.title or '图表'}"

    @tool
    def add_summary_section() -> str:
        """添加报告末尾的总结与建议章节。"""
        E.build_summary_section(doc, content.summary_items)
        return f"✓ 总结章节已添加（{len(content.summary_items)} 条摘要）"

    @tool
    def finalize_document() -> str:
        """完成文档编排，结束工具调用。必须在所有内容添加完毕后调用。"""
        return FINALIZE_SENTINEL

    return [
        add_cover_page,
        add_toc,
        add_kpi_cards,
        add_section_heading,
        add_narrative,
        add_stats_table,
        add_growth_indicators,
        add_dataframe_table,
        add_chart_data_table,
        add_summary_section,
        finalize_document,
    ]

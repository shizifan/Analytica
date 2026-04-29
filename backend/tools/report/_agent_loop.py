"""Shared LLM agent loop and outline serialisation for Skill-mode report generation.

Provides:
- ``serialize_outline`` — converts a *ReportOutline* into a compact text
  representation that fits an LLM's context window.
- ``run_report_agent`` — generic tool-calling agent loop used by the
  DOCX and HTML report skills (PPTX has no agent path).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Sequence

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from backend.tools.report._outline import (
    Block,
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

logger = logging.getLogger("analytica.tools.report._agent_loop")

FINALIZE_SENTINEL = "__FINALIZE__"

# ---------------------------------------------------------------------------
# Think-tag stripping (Qwen3 emits <think>…</think> blocks)
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think_tags(text: str) -> str:
    return _THINK_RE.sub("", text).strip()

    lines.append("## 指令")
    lines.append(
        "请使用上述内容组合一份完整的报告。"
        "section_index 对应 Section 编号，item_index 对应 Section 内 [] 编号。"
        "完成后务必调用 finalize 工具。"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Outline serialisation (Step 4+) — fed to LLM agent under outline pipeline
# ---------------------------------------------------------------------------

def _describe_block(block: Block, outline: ReportOutline) -> str:
    """One-line human-readable description for LLM context."""
    if isinstance(block, KpiRowBlock):
        labels = ", ".join(it.label for it in block.items[:4])
        return f"kpi_row: {len(block.items)} 张 ({labels})"
    if isinstance(block, ParagraphBlock):
        preview = block.text[:80].replace("\n", " ")
        return f'paragraph (style={block.style}): "{preview}..."'
    if isinstance(block, TableBlock):
        asset = outline.assets.get(block.asset_id)
        kind = asset.kind if asset else "?"
        return (
            f"table (asset={block.asset_id}, source={kind}): "
            f"{block.caption or '(no caption)'}"
        )
    if isinstance(block, ChartBlock):
        return f"chart (asset={block.asset_id}): {block.caption or '(no caption)'}"
    if isinstance(block, ChartTablePairBlock):
        return (
            f"chart_table_pair (chart={block.chart_asset_id}, "
            f"table={block.table_asset_id}, layout={block.layout})"
        )
    if isinstance(block, ComparisonGridBlock):
        titles = " / ".join(c.title for c in block.columns)
        return f"comparison_grid: {len(block.columns)} 列 ({titles})"
    if isinstance(block, GrowthIndicatorsBlock):
        return f"growth_indicators: {len(block.growth_rates)} 项"
    if isinstance(block, SectionCoverBlock):
        return f"section_cover: {block.title}"
    return f"unknown ({type(block).__name__})"


def serialize_outline(outline: ReportOutline) -> str:
    """Convert *outline* into compact text for the agent's user message.

    Each block is shown with its ``block_id`` so the LLM addresses
    blocks by ID, not by index. Section ordering matches outline.sections.
    """
    lines: list[str] = []
    lines.append("## 报告元数据")
    lines.append(f"- 标题: {outline.metadata.get('title', '')}")
    lines.append(f"- 作者: {outline.metadata.get('author', '')}")
    lines.append(f"- 日期: {outline.metadata.get('date', '')}")
    if outline.kpi_summary:
        kpi_preview = ", ".join(
            f"{k.label}={k.value}" for k in outline.kpi_summary[:4]
        )
        lines.append(f"- 全局 KPI: {len(outline.kpi_summary)} 张 ({kpi_preview})")
    lines.append("")

    lines.append("## 章节与块")
    for sec_idx, section in enumerate(outline.sections):
        lines.append(
            f'### Section {sec_idx} (role={section.role}): "{section.name}"'
        )
        if not section.blocks:
            lines.append("  (empty)")
        for block in section.blocks:
            lines.append(f"  [{block.block_id}] {_describe_block(block, outline)}")
        lines.append("")

    lines.append("## 指令")
    lines.append("请按以下顺序调用工具组装文档:")
    lines.append("1. begin_document")
    lines.append("2. 对每个 Section: begin_section(section_index) → "
                 "对该 section 的每个 block 调用对应 emit_*(block_id) → "
                 "end_section(section_index)")
    lines.append("3. finalize_document")
    lines.append("")
    lines.append("规则:")
    lines.append("- block_id 必须严格使用大纲中提供的 ID, 不要编造")
    lines.append("- 不要跳过 block, 不要重复调用同一 block")
    lines.append("- 完成后必须调用 finalize_document")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

async def run_report_agent(
    llm: Any,
    tools: Sequence[BaseTool],
    system_prompt: str,
    user_message: str,
    *,
    max_iterations: int = 15,
) -> bool:
    """Run a tool-calling agent loop.

    Returns ``True`` if the LLM successfully called the *finalize* tool,
    ``False`` if it exhausted iterations or stopped without finalising.
    """
    tool_map: dict[str, BaseTool] = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message),
    ]

    for iteration in range(max_iterations):
        response: AIMessage = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            logger.info("Agent stopped without tool calls at iteration %d", iteration)
            break

        for tc in tool_calls:
            name = tc["name"]
            args = tc["args"]
            tc_id = tc.get("id", name)

            tool = tool_map.get(name)
            if tool is None:
                err = f"Unknown tool '{name}'. Available: {list(tool_map.keys())}"
                logger.warning(err)
                messages.append(ToolMessage(content=f"✗ {err}", tool_call_id=tc_id))
                continue

            try:
                result = tool.invoke(args)
            except Exception as exc:
                result = f"✗ Tool error: {exc}"
                logger.warning("Tool %s raised: %s", name, exc)

            if result == FINALIZE_SENTINEL:
                logger.info("Agent finalised at iteration %d", iteration)
                return True

            messages.append(ToolMessage(content=str(result), tool_call_id=tc_id))

    logger.warning("Agent did not finalise within %d iterations", max_iterations)
    return False

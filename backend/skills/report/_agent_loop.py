"""Shared LLM agent loop and content serialisation for Skill-mode report generation.

Provides:
- ``serialize_report_content`` — converts a *ReportContent* object into a compact
  text representation that fits an LLM's context window.
- ``run_report_agent`` — generic tool-calling agent loop used by all three
  report skills (docx, pptx, html).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Sequence

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from backend.skills.report._content_collector import (
    ChartDataItem,
    DataFrameItem,
    GrowthItem,
    NarrativeItem,
    ReportContent,
    StatsTableItem,
    SummaryTextItem,
)

logger = logging.getLogger("analytica.skills.report._agent_loop")

FINALIZE_SENTINEL = "__FINALIZE__"

# ---------------------------------------------------------------------------
# Think-tag stripping (Qwen3 emits <think>…</think> blocks)
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think_tags(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


# ---------------------------------------------------------------------------
# Content serialisation
# ---------------------------------------------------------------------------

def _describe_item(item: Any) -> str:  # noqa: ANN401
    """Return a one-line human-readable description of a content item."""
    if isinstance(item, NarrativeItem):
        preview = item.text[:120].replace("\n", " ")
        return f'NarrativeItem: "{preview}..." ({len(item.text)} chars)'
    if isinstance(item, StatsTableItem):
        cols = list(item.summary_stats.keys())
        sample = item.summary_stats.get(cols[0], {}) if cols else {}
        metrics = list(sample.keys()) if isinstance(sample, dict) else []
        return f"StatsTableItem: columns={cols}, metrics={metrics}"
    if isinstance(item, GrowthItem):
        cols = list(item.growth_rates.keys())
        sample = item.growth_rates.get(cols[0], {}) if cols else {}
        flags = [k for k in sample if sample.get(k) is not None] if isinstance(sample, dict) else []
        return f"GrowthItem: columns={cols}, available={flags}"
    if isinstance(item, ChartDataItem):
        series_count = len(item.option.get("series", []))
        x_data = item.option.get("xAxis", {})
        cat_count = len(x_data.get("data", [])) if isinstance(x_data, dict) else 0
        return f'ChartDataItem: title="{item.title}", categories={cat_count}, series={series_count}'
    if isinstance(item, DataFrameItem):
        shape = item.df.shape
        cols = list(item.df.columns)
        return f"DataFrameItem: shape={shape}, columns={cols}"
    if isinstance(item, SummaryTextItem):
        preview = item.text[:120].replace("\n", " ")
        return f'SummaryTextItem: "{preview}..." ({len(item.text)} chars)'
    return f"UnknownItem({type(item).__name__})"


def serialize_report_content(content: ReportContent) -> str:
    """Convert *ReportContent* into a compact, indexed text representation."""
    lines: list[str] = []

    lines.append("## 报告元数据")
    lines.append(f"- 标题: {content.title}")
    lines.append(f"- 作者: {content.author}")
    lines.append(f"- 日期: {content.date}")
    lines.append("")
    lines.append("## 章节内容")

    for sec_idx, section in enumerate(content.sections):
        lines.append(f'### Section {sec_idx}: "{section.name}"')
        if not section.items:
            lines.append("  (empty)")
        for item_idx, item in enumerate(section.items):
            lines.append(f"  [{item_idx}] {_describe_item(item)}")
        lines.append("")

    if content.summary_items:
        lines.append("## 摘要内容")
        for i, si in enumerate(content.summary_items):
            lines.append(f"  [{i}] {_describe_item(si)}")
        lines.append("")

    lines.append("## 指令")
    lines.append(
        "请使用上述内容组合一份完整的报告。"
        "section_index 对应 Section 编号，item_index 对应 Section 内 [] 编号。"
        "完成后务必调用 finalize 工具。"
    )

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

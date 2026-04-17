"""Shared content extraction and section-association logic.

Replaces the duplicated (and buggy) content-collection code formerly
inlined in docx_gen, pptx_gen and html_gen.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger("analytica.skills.report._content_collector")

# ---------------------------------------------------------------------------
# Content item types
# ---------------------------------------------------------------------------

@dataclass
class NarrativeItem:
    text: str
    source_task: str = ""

@dataclass
class StatsTableItem:
    summary_stats: dict[str, Any]
    source_task: str = ""

@dataclass
class GrowthItem:
    growth_rates: dict[str, dict[str, float | None]]
    source_task: str = ""

@dataclass
class ChartDataItem:
    option: dict[str, Any]
    title: str = ""
    source_task: str = ""

@dataclass
class DataFrameItem:
    df: pd.DataFrame
    source_task: str = ""

@dataclass
class SummaryTextItem:
    text: str
    source_task: str = ""

ContentItem = NarrativeItem | StatsTableItem | GrowthItem | ChartDataItem | DataFrameItem | SummaryTextItem

# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------

@dataclass
class SectionContent:
    name: str
    items: list[ContentItem] = field(default_factory=list)

@dataclass
class ReportContent:
    title: str
    author: str
    date: str
    sections: list[SectionContent] = field(default_factory=list)
    summary_items: list[SummaryTextItem] = field(default_factory=list)

# ---------------------------------------------------------------------------
# Section normalisation
# ---------------------------------------------------------------------------

def _normalize_sections(raw: list) -> list[dict[str, Any]]:
    """Accept both old ``["name", ...]`` and new ``[{"name": ..., "task_refs": [...]}, ...]``."""
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append({"name": item.get("name", ""), "task_refs": list(item.get("task_refs", []))})
        elif isinstance(item, str):
            out.append({"name": item, "task_refs": []})
    return out

# ---------------------------------------------------------------------------
# Core: extract content items from context
# ---------------------------------------------------------------------------

def _extract_items(context: dict[str, Any]) -> tuple[list[ContentItem], list[SummaryTextItem]]:
    """Walk *context* and classify every upstream SkillOutput."""
    items: list[ContentItem] = []
    summaries: list[SummaryTextItem] = []

    for task_id in sorted(context.keys()):
        task_output = context[task_id]
        data = task_output.data if hasattr(task_output, "data") else (
            task_output.get("data") if isinstance(task_output, dict) else None
        )

        if isinstance(data, pd.DataFrame) and not data.empty:
            items.append(DataFrameItem(df=data, source_task=task_id))
            continue

        if isinstance(data, str):
            summaries.append(SummaryTextItem(text=data, source_task=task_id))
            continue

        if not isinstance(data, dict):
            continue

        # Narrative
        narrative = data.get("narrative")
        if narrative and isinstance(narrative, str) and len(narrative) > 10:
            items.append(NarrativeItem(text=narrative, source_task=task_id))

        # Summary stats
        stats = data.get("summary_stats")
        if isinstance(stats, dict) and stats:
            items.append(StatsTableItem(summary_stats=stats, source_task=task_id))

        # Growth rates
        growth = data.get("growth_rates")
        if isinstance(growth, dict) and growth:
            items.append(GrowthItem(growth_rates=growth, source_task=task_id))

        # Chart data (ECharts option with series)
        if "series" in data:
            chart_title = ""
            title_obj = data.get("title")
            if isinstance(title_obj, dict):
                chart_title = title_obj.get("text", "")
            elif isinstance(title_obj, str):
                chart_title = title_obj
            items.append(ChartDataItem(option=data, title=chart_title, source_task=task_id))

        # Summary text field
        summary_text = data.get("summary")
        if isinstance(summary_text, str) and summary_text:
            summaries.append(SummaryTextItem(text=summary_text, source_task=task_id))

    return items, summaries

# ---------------------------------------------------------------------------
# Core: associate items to sections via task_refs or sequential fallback
# ---------------------------------------------------------------------------

def _associate(sections: list[dict[str, Any]], items: list[ContentItem]) -> list[SectionContent]:
    """Assign *items* to *sections*.

    Strategy:
      - If **any** section carries ``task_refs`` → *direct mapping*: each item
        is placed in the section whose ``task_refs`` list contains its
        ``source_task``.  Unmatched items go to the least-populated section.
      - Otherwise (backward-compatible path) → *sequential distribution*:
        items are grouped by ``source_task`` order, then groups are assigned
        to sections round-robin.
    """
    if not sections:
        sections = [{"name": "数据概览", "task_refs": []}]

    result = [SectionContent(name=s["name"]) for s in sections]

    has_refs = any(s.get("task_refs") for s in sections)

    if has_refs:
        # ── Direct mapping via task_refs ──
        assigned: set[int] = set()
        for sec_idx, sec in enumerate(sections):
            refs = set(sec.get("task_refs", []))
            if not refs:
                continue
            for item_idx, item in enumerate(items):
                if item.source_task in refs:
                    result[sec_idx].items.append(item)
                    assigned.add(item_idx)

        # Unmatched items → least-populated section
        for item_idx, item in enumerate(items):
            if item_idx not in assigned:
                target = min(range(len(result)), key=lambda i: len(result[i].items))
                result[target].items.append(item)
    else:
        # ── Fallback: sequential by task order ──
        from collections import OrderedDict

        task_groups: OrderedDict[str, list[ContentItem]] = OrderedDict()
        for item in items:
            task_groups.setdefault(item.source_task, []).append(item)

        groups = list(task_groups.values())
        for g_idx, group in enumerate(groups):
            target_idx = g_idx % len(result)
            result[target_idx].items.extend(group)

    return result

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect_and_associate(params: dict[str, Any], context: dict[str, Any]) -> ReportContent:
    """Extract metadata, classify upstream outputs, and associate to sections.

    This is the single entry point used by docx_gen, pptx_gen and html_gen.
    """
    report_metadata = params.get("report_metadata", {})
    if not isinstance(report_metadata, dict):
        report_metadata = {}
    report_structure = params.get("report_structure", {})
    if not isinstance(report_structure, dict):
        report_structure = {}

    title = report_metadata.get("title", "数据分析报告")
    author = report_metadata.get("author", "Analytica")
    date = report_metadata.get("date", "")
    raw_sections = report_structure.get("sections", [])
    if not isinstance(raw_sections, list):
        raw_sections = []

    sections = _normalize_sections(raw_sections)

    # Auto-generate section names from context when LLM provides none
    if not sections:
        for task_id, task_output in context.items():
            data = task_output.data if hasattr(task_output, "data") else None
            if isinstance(data, dict) and "narrative" in data:
                sections.append({"name": f"分析 - {task_id}", "task_refs": [task_id]})
        if not sections:
            sections = [{"name": "数据概览", "task_refs": []}, {"name": "分析总结", "task_refs": []}]

    items, summaries = _extract_items(context)
    associated = _associate(sections, items)

    return ReportContent(
        title=title,
        author=author,
        date=date,
        sections=associated,
        summary_items=summaries,
    )

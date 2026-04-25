"""Shared content extraction and section-association logic.

Replaces the duplicated (and buggy) content-collection code formerly
inlined in docx_gen, pptx_gen and html_gen.

Batch 4 changes:
- Iterate context in task-declaration order (falls back to sorted dict keys
  only when no order is supplied). Previously the ``sorted(keys)`` path
  interleaved content in lexicographic order — e.g. T001 → T010 → T011 →
  T002 — which in turn shuffled items across sections because task_refs
  matching happened in the same pass.
- Skip task outputs whose status is ``failed`` or ``skipped`` — those carry
  either None or stale data and should never be rendered.
- Drop unmatched items (log a warning) instead of padding the least-full
  section, which produced the observed "wrong content in wrong chapter"
  effect.
- KPI cards are extracted asynchronously by each report generator via
  ``_kpi_extractor.extract_kpis_llm`` after collect_and_associate() returns.
- Normalise DataFrame items: unit-annotated headers, sort-by-first-numeric
  descending, Top-N + "其他" row merge.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.tools._i18n import col_label
from backend.tools.report._kpi_extractor import KPIItem

logger = logging.getLogger("analytica.tools.report._content_collector")

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
    kpi_cards: list[KPIItem] = field(default_factory=list)  # batch 4

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

# ── Narrative filter: drop LLM failure tags that descriptive.py emits ──

_FAILED_NARRATIVE_PREFIXES = ("[narrative_failed:", "[自动生成失败]")


def _is_failed_narrative(text: str) -> bool:
    return any(text.startswith(p) for p in _FAILED_NARRATIVE_PREFIXES)


# ── DataFrame normalisation (batch 4 S4-6) ───────────────────────

def normalize_dataframe_item(
    item: "DataFrameItem",
    max_rows: int = 8,
) -> "DataFrameItem":
    """Return a cleaned DataFrameItem suitable for rendering.

    Transforms:
    - Translate column headers to Chinese using ``col_label()`` from _i18n.
    - Sort descending by first numeric column (makes TOP-N meaningful).
    - If more than ``max_rows`` rows, keep top (max_rows-1) and append an
      "其他" row summing the remaining numeric columns.

    No-ops when the DataFrame is empty or doesn't have a numeric column.
    """
    df = item.df
    if df is None or df.empty:
        return item

    df = df.copy()
    # Rename only columns that have a Chinese translation and whose target
    # label is not already taken (prevents duplicate column names when
    # e.g. both "dateMonth" and "month" would map to "月份").
    rename_map: dict[str, str] = {}
    target_seen: set[str] = set(df.columns)  # existing names that must stay unique
    for c in df.columns:
        target = col_label(c)
        if target != c and target not in target_seen:
            rename_map[c] = target
            target_seen.add(target)
        elif target != c and target not in rename_map.values():
            # target already used by another column; keep original name
            pass
    if rename_map:
        df = df.rename(columns=rename_map)

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if numeric_cols:
        try:
            df = df.sort_values(numeric_cols[0], ascending=False, kind="stable")
        except Exception:
            pass  # defensive — sorting is best-effort

    if len(df) > max_rows:
        top = df.head(max_rows - 1)
        rest = df.iloc[max_rows - 1:]
        other_row: dict[str, Any] = {}
        for c in df.columns:
            if pd.api.types.is_numeric_dtype(df[c]):
                try:
                    other_row[c] = float(pd.to_numeric(rest[c], errors="coerce").sum())
                except Exception:
                    other_row[c] = None
            else:
                other_row[c] = "其他合计"
        df = pd.concat([top, pd.DataFrame([other_row])], ignore_index=True)

    return DataFrameItem(df=df, source_task=item.source_task)


# ── Extract: classifies upstream ToolOutput objects into content items ──

def _extract_items(
    context: dict[str, Any],
    task_order: list[str] | None = None,
) -> tuple[list[ContentItem], list[SummaryTextItem]]:
    """Walk *context* and classify every upstream ToolOutput.

    Iteration order:
      - ``task_order`` (when supplied) — preserves the template's logical
        sequence so downstream sections stay coherent.
      - otherwise falls back to ``sorted(context.keys())`` — lexicographic,
        which is the pre-batch-4 behaviour and is retained for callers that
        still don't thread ``task_order`` through.

    Skips ToolOutputs whose ``status`` is ``failed`` or ``skipped`` —
    those outputs either carry None or stale data (and contained the
    ``[narrative_failed:*]`` tag when the LLM call failed).
    """
    items: list[ContentItem] = []
    summaries: list[SummaryTextItem] = []

    if task_order:
        # Preserve declared order; append any trailing keys that weren't in
        # the declared list (defensive — execute_plan may have added
        # auxiliary outputs).
        seen = set(task_order)
        keys = list(task_order) + [k for k in context.keys() if k not in seen]
    else:
        keys = sorted(context.keys())

    for task_id in keys:
        if task_id not in context:
            continue
        task_output = context[task_id]
        status = getattr(task_output, "status", "success")
        if status in ("failed", "skipped"):
            continue

        data = task_output.data if hasattr(task_output, "data") else (
            task_output.get("data") if isinstance(task_output, dict) else None
        )

        if isinstance(data, pd.DataFrame) and not data.empty:
            items.append(normalize_dataframe_item(
                DataFrameItem(df=data, source_task=task_id),
            ))
            continue

        if isinstance(data, str):
            if not _is_failed_narrative(data):
                summaries.append(SummaryTextItem(text=data, source_task=task_id))
            continue

        if not isinstance(data, dict):
            continue

        # Narrative — filter out failure tags emitted by descriptive/summary
        narrative = data.get("narrative")
        if (narrative and isinstance(narrative, str)
                and len(narrative) > 10 and not _is_failed_narrative(narrative)):
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
        if (isinstance(summary_text, str) and summary_text
                and not _is_failed_narrative(summary_text)):
            summaries.append(SummaryTextItem(text=summary_text, source_task=task_id))

    return items, summaries

# ---------------------------------------------------------------------------
# Core: associate items to sections via task_refs or sequential fallback
# ---------------------------------------------------------------------------

def _associate(sections: list[dict[str, Any]], items: list[ContentItem]) -> list[SectionContent]:
    """Assign *items* to *sections* based on ``task_refs``.

    Strategy:
      - If **any** section carries ``task_refs`` → *direct mapping*: each item
        is placed in the section whose ``task_refs`` list contains its
        ``source_task``. Unmatched items are **dropped with a warning log**
        (batch 4 change — previously they were stuffed into the least-full
        section, which produced cross-section misassignment).
      - Otherwise (no task_refs declared anywhere) → *sequential distribution*:
        items are grouped by ``source_task`` order, then groups are assigned
        to sections round-robin (backward-compatible fallback).
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

        # Unmatched items → drop with log (batch 4 change)
        unmatched = [items[i] for i in range(len(items)) if i not in assigned]
        if unmatched:
            dropped_sources = sorted({it.source_task for it in unmatched})
            logger.warning(
                "Dropping %d unmatched report items (sources=%s); "
                "check report_structure.task_refs coverage",
                len(unmatched), dropped_sources,
            )
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

def collect_and_associate(
    params: dict[str, Any],
    context: dict[str, Any],
    task_order: list[str] | None = None,
) -> ReportContent:
    """Extract metadata, classify upstream outputs, and associate to sections.

    Single entry point used by docx_gen, pptx_gen, html_gen, markdown_gen.

    Args:
        params: skill params — reads ``report_metadata``, ``report_structure``,
            and ``_template_meta`` (injected by execute_plan / test harness).
        context: execution context mapping task_id → ToolOutput.
        task_order: optional ordered list of task_ids (from the original
            plan). Used for iteration in _extract_items so item ordering
            mirrors the template's logical flow instead of lexicographic.
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

    items, summaries = _extract_items(context, task_order=task_order)
    associated = _associate(sections, items)

    # KPI cards are populated asynchronously by each report generator
    # after collect_and_associate() returns, via extract_kpis_llm().
    return ReportContent(
        title=title,
        author=author,
        date=date,
        sections=associated,
        summary_items=summaries,
        kpi_cards=[],
    )

"""Legacy ReportContent → ReportOutline converter — Step 3.

Bridges Stage 1 (``collect_and_associate``, the existing content
collector) and Stage 3 (``BlockRenderer``) during the migration. This
mapping is 1:1: every existing ContentItem becomes one Block (plus, for
table/chart/stats, a registered Asset) and section roles are inferred
heuristically from section names.

Will be retired in Step 8 when ``_outline_planner.plan_outline``
replaces this with an LLM-driven path (and a rule-based fallback that
still uses this same logic).
"""
from __future__ import annotations

from typing import Any

from backend.tools.report._content_collector import (
    ChartDataItem,
    ContentItem,
    DataFrameItem,
    GrowthItem,
    NarrativeItem,
    StatsTableItem,
    collect_and_associate,
)
from backend.tools.report._kpi_extractor import KPIItem
from backend.tools.report._outline import (
    Asset,
    Block,
    ChartAsset,
    ChartBlock,
    GrowthIndicatorsBlock,
    OutlineSection,
    ParagraphBlock,
    ReportOutline,
    SectionRole,
    StatsAsset,
    TableAsset,
    TableBlock,
    new_asset_id,
    new_block_id,
    reset_id_counters,
)


def collect_and_build_outline(
    params: dict[str, Any],
    context: dict[str, Any],
    *,
    task_order: list[str] | None = None,
    kpi_cards: list[KPIItem] | None = None,
) -> ReportOutline:
    """Run legacy collection + map result onto a ``ReportOutline``.

    The four ``*_gen.py`` modules pass in ``kpi_cards`` separately
    because they currently own the ``extract_kpis_llm`` call; Step 8
    folds that into the planner.
    """
    reset_id_counters()
    rc = collect_and_associate(params, context, task_order=task_order)

    outline = ReportOutline(
        metadata={
            "title": rc.title,
            "author": rc.author,
            "date": rc.date,
            "intent": params.get("intent", ""),
        },
        kpi_summary=list(kpi_cards or []),
        degradations=list(rc.degradations),
        planner_mode="rule_fallback",
    )

    for old_sec in rc.sections:
        new_sec = OutlineSection(
            name=old_sec.name,
            role=_infer_role(old_sec.name),
            blocks=[],
            source_tasks=[],
        )
        for item in old_sec.items:
            block, asset = _convert_item(item)
            if asset is not None:
                outline.assets[asset.asset_id] = asset
            if block is not None:
                new_sec.blocks.append(block)
            if item.source_task and item.source_task not in new_sec.source_tasks:
                new_sec.source_tasks.append(item.source_task)
        outline.sections.append(new_sec)

    # Append the appendix that legacy markdown/docx render as "总结与建议".
    # An empty appendix is intentional — each renderer has its own
    # convention for the default sentence (DOCX: grey italic, Markdown:
    # bullet) so that lives in the renderer, not here.
    appendix = OutlineSection(name="总结与建议", role="appendix")
    for si in rc.summary_items:
        appendix.blocks.append(ParagraphBlock(
            block_id=new_block_id(),
            text=si.text,
            style="lead",
        ))
        if si.source_task and si.source_task not in appendix.source_tasks:
            appendix.source_tasks.append(si.source_task)
    outline.sections.append(appendix)

    return outline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_role(name: str) -> SectionRole:
    if any(k in name for k in ("摘要", "概览", "执行摘要")):
        return "summary"
    if any(k in name for k in ("建议", "结论", "总结")):
        return "recommendation"
    if any(k in name for k in ("归因", "原因")):
        return "attribution"
    return "status"


def _convert_item(item: ContentItem) -> tuple[Block | None, Asset | None]:
    if isinstance(item, NarrativeItem):
        return ParagraphBlock(
            block_id=new_block_id(),
            text=item.text,
            style="body",
        ), None

    if isinstance(item, StatsTableItem):
        asset = StatsAsset(
            asset_id=new_asset_id("stats"),
            source_task=item.source_task,
            summary_stats=item.summary_stats,
        )
        return TableBlock(
            block_id=new_block_id(),
            asset_id=asset.asset_id,
            caption="统计数据概览",
        ), asset

    if isinstance(item, GrowthItem):
        return GrowthIndicatorsBlock(
            block_id=new_block_id(),
            growth_rates=item.growth_rates,
        ), None

    if isinstance(item, ChartDataItem):
        asset = ChartAsset(
            asset_id=new_asset_id("chart"),
            source_task=item.source_task,
            option=item.option,
            endpoint=item.endpoint_name,
        )
        return ChartBlock(
            block_id=new_block_id(),
            asset_id=asset.asset_id,
            caption=item.title or "图表",
        ), asset

    if isinstance(item, DataFrameItem):
        df = item.df
        asset = TableAsset(
            asset_id=new_asset_id("table"),
            source_task=item.source_task,
            df_records=df.to_dict(orient="records"),
            columns_meta=[{"name": str(c)} for c in df.columns],
            endpoint=item.endpoint_name,
        )
        return TableBlock(
            block_id=new_block_id(),
            asset_id=asset.asset_id,
            caption="数据明细",
        ), asset

    return None, None

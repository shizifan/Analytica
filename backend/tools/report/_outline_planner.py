"""Outline planner — LLM-driven Stage-2 entry point.

``plan_outline`` runs ``collect_and_associate`` (Stage 1), prepares
asset/item summaries, calls the LLM once to produce a complete outline
(``kpi_summary`` + ``sections.blocks`` + synthesised blocks like the
attribution table or recommendation grid), validates it against the
asset registry, and returns a ``ReportOutline`` ready for rendering.

There is no rule-based fallback: when the LLM fails, the call raises
``_LLMPlannerFailure`` and the caller must decide how to surface the
error. Keeping a single planning path eliminates the silent
divergence that the previous fallback could mask.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.config import get_settings
from backend.tools._llm import invoke_llm
from backend.tools.report._content_collector import (
    ChartDataItem,
    ContentItem,
    DataFrameItem,
    GrowthItem,
    NarrativeItem,
    ReportContent,
    StatsTableItem,
    SummaryTextItem,
    collect_and_associate,
)
from backend.tools.report._outline import (
    Asset,
    Block,
    ChartAsset,
    ChartBlock,
    ChartTablePairBlock,
    ComparisonGridBlock,
    GridColumn,
    GrowthIndicatorsBlock,
    KPIItem,
    KpiRowBlock,
    KpiStripBlock,
    KpiStripItem,
    OutlineSection,
    ParagraphBlock,
    ReportOutline,
    SectionCoverBlock,
    SectionRole,
    StatsAsset,
    TableAsset,
    TableBlock,
    new_asset_id,
    new_block_id,
    reset_id_counters,
)
from backend.tools.report._planner_prompts import (
    OUTLINE_PLANNER_SYSTEM,
    build_planner_user_prompt,
)


logger = logging.getLogger("analytica.tools.report._outline_planner")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

class _LLMPlannerFailure(Exception):
    """Raised when the LLM planner output is unusable.

    Wraps any failure mode (network error, malformed JSON, schema
    violation, dangling asset_id, …). Callers that need a usable
    outline must handle this — there is no built-in fallback.
    """


async def plan_outline(
    params: dict[str, Any],
    context: dict[str, Any],
    *,
    task_order: list[str] | None = None,
    intent: str = "",
    task_id: str = "",
    span_emit: Any = None,
) -> ReportOutline:
    """Return a ``ReportOutline`` ready for rendering.

    Pipeline:
      1. ``collect_and_associate`` runs Stage-1 collection.
      2. Convert items → assets (without binding to sections).
      3. Build prompt + call LLM.
      4. Parse + validate JSON response (schema + asset_id existence).
      5. Compose ``ReportOutline`` from validated response.

    Raises ``_LLMPlannerFailure`` when the LLM call fails or the
    response is malformed.
    """
    # ── Multi-turn: load previous artifacts' execution context ──────
    _previous_artifacts = params.get("_previous_artifacts", [])
    if _previous_artifacts:
        from backend.memory.artifact_store import read_conversion_context
        _merged_count = 0
        for art in _previous_artifacts:
            art_id = art.get("artifact_id", "")
            if not art_id:
                continue
            prev_ctx = read_conversion_context(art_id)
            if prev_ctx is None:
                continue

            # Restore previous task order (may be needed for collection)
            if task_order is None:
                task_order = prev_ctx.get("task_order")

            # Merge previous context into current — current turn data
            # takes precedence (skip keys already present).
            for tid, val in prev_ctx.get("context", {}).items():
                if tid not in context:
                    context[tid] = val
                    _merged_count += 1

        if _merged_count > 0:
            logger.info(
                "plan_outline: merged %d previous artifacts into context "
                "from %d sources",
                _merged_count, len(_previous_artifacts),
            )

    rc = collect_and_associate(params, context, task_order=task_order)

    reset_id_counters()
    assets, items_by_task = _items_to_assets(rc)

    section_defs = [
        {"name": s.name, "role": _infer_role(s.name)}
        for s in rc.sections
    ]
    user_prompt = build_planner_user_prompt(
        intent or rc.title,
        section_defs,
        _summarise_assets(assets),
        _summarise_raw_items(rc, items_by_task),
    )

    settings = get_settings()
    result = await invoke_llm(
        user_prompt,
        system_prompt=OUTLINE_PLANNER_SYSTEM,
        temperature=settings.LLM_TEMPERATURE_DEFAULT,
        timeout=60,
        span_emit=span_emit,
        task_id=task_id,
    )
    if result.get("error"):
        raise _LLMPlannerFailure(
            f"LLM error [{result.get('error_category')}]: {result.get('error')}"
        )

    parsed = _parse_outline_json(result.get("text", ""))
    if parsed is None:
        raise _LLMPlannerFailure("LLM output not valid JSON")

    # Phase 3.4: register LLM-synthesised assets (e.g. attribution
    # tables) before validation, so block ``asset_id`` references to
    # these new ids resolve cleanly.
    _consume_synthesised_assets(parsed, assets)

    _validate_outline_response(parsed, assets, section_defs)

    return _build_outline_from_response(
        parsed, rc, assets, section_defs, intent,
    )


# ---------------------------------------------------------------------------
# Section role inference (was _outline_legacy._infer_role — moved here so
# the planner is self-contained after the rule-fallback removal).
# ---------------------------------------------------------------------------

def _infer_role(name: str) -> SectionRole:
    if any(k in name for k in ("摘要", "概览", "执行摘要")):
        return "summary"
    if any(k in name for k in ("建议", "结论", "总结")):
        return "recommendation"
    if any(k in name for k in ("归因", "原因")):
        return "attribution"
    return "status"


# ---------------------------------------------------------------------------
# ContentItem → (Block, Asset) conversion (was _outline_legacy._convert_item).
# Used to build the asset registry from Stage-1 items so the LLM has a
# concrete catalogue to reference when planning blocks.
# ---------------------------------------------------------------------------

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

    if isinstance(item, SummaryTextItem):
        return ParagraphBlock(
            block_id=new_block_id(),
            text=item.text,
            style="lead",
        ), None

    return None, None


# ---------------------------------------------------------------------------
# LLM input prep — stage 1 → assets
# ---------------------------------------------------------------------------

def _items_to_assets(
    rc: ReportContent,
) -> tuple[dict[str, Asset], dict[str, list[tuple[Block, Asset | None]]]]:
    """Convert all ContentItems to (block, asset) pairs without binding
    to sections. Returns ``(assets_by_id, items_grouped_by_source_task)``.
    """
    assets: dict[str, Asset] = {}
    by_task: dict[str, list[tuple[Block, Asset | None]]] = {}
    for sec in rc.sections:
        for item in sec.items:
            block, asset = _convert_item(item)
            if asset is not None:
                assets[asset.asset_id] = asset
            if block is not None:
                by_task.setdefault(item.source_task, []).append((block, asset))
    return assets, by_task


def _summarise_assets(assets: dict[str, Asset]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for aid, asset in assets.items():
        if isinstance(asset, ChartAsset):
            xa = asset.option.get("xAxis", {})
            cats = xa.get("data", []) if isinstance(xa, dict) else []
            series = asset.option.get("series", [])
            stype = series[0].get("type") if series else None
            out.append({
                "asset_id": aid, "kind": "chart",
                "source_task": asset.source_task,
                "preview": (
                    f"{stype} chart, {len(cats)} categories, "
                    f"{len(series)} series"
                ),
            })
        elif isinstance(asset, TableAsset):
            cols = [c.get("name") for c in asset.columns_meta]
            out.append({
                "asset_id": aid, "kind": "table",
                "source_task": asset.source_task,
                "preview": (
                    f"{len(asset.df_records)} rows, columns: {cols}"
                ),
            })
        elif isinstance(asset, StatsAsset):
            cols = list(asset.summary_stats.keys())
            out.append({
                "asset_id": aid, "kind": "stats",
                "source_task": asset.source_task,
                "preview": f"summary_stats columns: {cols}",
            })
    return out


def _summarise_raw_items(
    rc: ReportContent,
    items_by_task: dict[str, list[tuple[Block, Asset | None]]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tid, pairs in items_by_task.items():
        out.append({
            "task_id": tid,
            "block_kinds_available": [b.kind for b, _ in pairs],
        })
    for si in rc.summary_items:
        out.append({
            "task_id": si.source_task,
            "block_kinds_available": ["paragraph(style=lead)"],
            "preview": si.text[:80],
        })
    return out


# ---------------------------------------------------------------------------
# LLM output parsing + validation
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_outline_json(text: str) -> dict[str, Any] | None:
    text = _THINK_RE.sub("", text).strip()
    m = _JSON_FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        # Fallback: extract first {...} blob (some LLMs prepend chatter)
        m = _OBJECT_RE.search(text)
        if m:
            try:
                d = json.loads(m.group())
                return d if isinstance(d, dict) else None
            except json.JSONDecodeError:
                return None
        return None


def _consume_synthesised_assets(
    parsed: dict[str, Any],
    assets: dict[str, Asset],
) -> None:
    """Register the LLM-synthesised assets payload (Phase 3.4).

    The planner prompt allows LLM to declare extra TableAssets it
    fabricated (e.g. an attribution summary table) under a top-level
    ``synthesised_assets`` array. We register them under their declared
    ``asset_id`` so block validation finds them.

    Quietly ignores malformed entries — they'll fail downstream
    validation if a block actually references them.
    """
    raw = parsed.get("synthesised_assets") or []
    if not isinstance(raw, list):
        return
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        aid = entry.get("asset_id")
        kind = entry.get("kind")
        if not isinstance(aid, str) or not aid or aid in assets:
            continue
        if kind == "table":
            records = entry.get("df_records") or []
            cols_meta = entry.get("columns_meta") or []
            if not isinstance(records, list):
                continue
            assets[aid] = TableAsset(
                asset_id=aid,
                source_task=entry.get("source_task", "synthesised"),
                df_records=[r for r in records if isinstance(r, dict)],
                columns_meta=[
                    c for c in cols_meta if isinstance(c, dict)
                ],
                endpoint=entry.get("endpoint"),
            )
        elif kind == "stats":
            stats = entry.get("summary_stats") or {}
            if not isinstance(stats, dict):
                continue
            assets[aid] = StatsAsset(
                asset_id=aid,
                source_task=entry.get("source_task", "synthesised"),
                summary_stats=stats,
                endpoint=entry.get("endpoint"),
            )
        # ChartAsset synthesis is not allowed — LLM cannot fabricate
        # raw chart data without ground truth from real tasks.


_VALID_BLOCK_KINDS = {
    "kpi_row", "paragraph", "table", "chart",
    "chart_table_pair", "comparison_grid", "growth_indicators",
}


def _validate_outline_response(
    parsed: dict[str, Any],
    assets: dict[str, Asset],
    section_defs: list[dict[str, str]],
) -> None:
    if "sections" not in parsed:
        raise _LLMPlannerFailure("response missing 'sections'")
    sections = parsed["sections"]
    if not isinstance(sections, list):
        raise _LLMPlannerFailure("'sections' must be a list")
    if len(sections) != len(section_defs):
        raise _LLMPlannerFailure(
            f"sections count mismatch: got {len(sections)}, "
            f"expected {len(section_defs)}"
        )

    asset_ids = set(assets.keys())
    for sec_idx, sec in enumerate(sections):
        if not isinstance(sec, dict):
            raise _LLMPlannerFailure(f"section[{sec_idx}] not a dict")
        blocks = sec.get("blocks", [])
        if not isinstance(blocks, list):
            raise _LLMPlannerFailure(f"section[{sec_idx}].blocks not a list")
        for b_idx, blk in enumerate(blocks):
            if not isinstance(blk, dict):
                raise _LLMPlannerFailure(
                    f"section[{sec_idx}].blocks[{b_idx}] not a dict"
                )
            kind = blk.get("kind")
            if kind not in _VALID_BLOCK_KINDS:
                raise _LLMPlannerFailure(
                    f"section[{sec_idx}].blocks[{b_idx}] unknown kind: {kind!r}"
                )
            for field_name in ("asset_id", "chart_asset_id", "table_asset_id"):
                if field_name in blk:
                    aid = blk[field_name]
                    if aid not in asset_ids:
                        raise _LLMPlannerFailure(
                            f"section[{sec_idx}].blocks[{b_idx}]."
                            f"{field_name}={aid!r} not in available assets"
                        )


def _deduplicate_chart_blocks(outline: ReportOutline) -> None:
    """Replace duplicate ChartBlocks (same asset_id across sections) with
    a light text reference so the same chart does not render on multiple
    pages.  The first occurrence of each asset_id is kept; subsequent
    occurrences become a ParagraphBlock citing the original section.
    """
    seen: dict[str, str] = {}  # asset_id → first_section_name
    for sec in outline.sections:
        new_blocks: list = []
        for blk in sec.blocks:
            if blk.kind == "chart" and hasattr(blk, "asset_id"):
                aid = blk.asset_id
                if aid in seen:
                    new_blocks.append(ParagraphBlock(
                        block_id=new_block_id(),
                        text=f"图表“{getattr(blk, 'caption', '数据图')}”详见"
                             f"「{seen[aid]}」部分，此处不再重复展示。",
                        style="body",
                    ))
                    continue
                seen[aid] = sec.name
            new_blocks.append(blk)
        sec.blocks = new_blocks


# ---------------------------------------------------------------------------
# Build outline from validated response
# ---------------------------------------------------------------------------

def _build_outline_from_response(
    parsed: dict[str, Any],
    rc: ReportContent,
    assets: dict[str, Asset],
    section_defs: list[dict[str, str]],
    intent: str,
) -> ReportOutline:
    kpi_summary: list[KPIItem] = []
    for k in parsed.get("kpi_summary", []) or []:
        if not isinstance(k, dict) or not k.get("label") or not k.get("value"):
            continue
        trend = k.get("trend")
        if trend not in ("positive", "negative"):
            trend = None
        kpi_summary.append(KPIItem(
            label=str(k["label"]),
            value=str(k["value"]),
            sub=str(k.get("sub") or ""),
            trend=trend,
        ))

    outline = ReportOutline(
        metadata={
            "title": rc.title, "author": rc.author,
            "date": rc.date, "intent": intent,
        },
        kpi_summary=kpi_summary,
        assets=dict(assets),
        degradations=list(rc.degradations),
        planner_mode="llm",
    )

    # Auto-inject SectionCoverBlock for each non-appendix section. The
    # LLM must NOT emit section_cover blocks itself — the prompt forbids
    # it and the validator rejects unknown kinds. Subtitle is intentionally
    # blank: the planner currently has no way to reason about a tagline,
    # and renderers degrade cleanly when subtitle is empty.
    cover_index = 0
    for sec_idx, sec_def in enumerate(section_defs):
        sec_resp = parsed["sections"][sec_idx]
        new_sec = OutlineSection(
            name=sec_def["name"],
            role=sec_def["role"],
            source_tasks=[
                str(t) for t in sec_resp.get("source_tasks", [])
                if isinstance(t, str)
            ],
        )
        if sec_def["role"] != "appendix":
            cover_index += 1
            new_sec.blocks.append(SectionCoverBlock(
                block_id=new_block_id(),
                index=cover_index,
                title=sec_def["name"],
            ))
        for blk_resp in sec_resp.get("blocks", []) or []:
            block = _block_from_response(blk_resp)
            if block is not None:
                new_sec.blocks.append(block)
        outline.sections.append(new_sec)

    _deduplicate_chart_blocks(outline)

    return outline


# Whitelisted semantic colors that the renderers know how to resolve
# (see ``_table_highlight.resolve_color``). LLM-emitted rules whose
# ``color`` falls outside this set are dropped — silent because picking a
# valid color is the LLM's job and a stray non-standard value shouldn't
# tank the whole table.
_HIGHLIGHT_COLOR_WHITELIST = frozenset({
    "positive", "negative", "neutral", "accent",
    "gold", "silver", "bronze",
})


def _parse_highlight_rules(raw: Any) -> list[dict[str, Any]]:
    """Whitelist-validate ``TableBlock.highlight_rules`` from LLM JSON.

    Each rule must specify a ``color`` from the whitelist plus EITHER a
    ``col`` (column name) OR a ``row`` (0-based int after header). The
    optional ``predicate`` string is passed through verbatim — the
    renderer interprets / ignores unknown predicates.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        color = r.get("color")
        if color not in _HIGHLIGHT_COLOR_WHITELIST:
            continue
        col = r.get("col")
        row = r.get("row")
        if col is None and row is None:
            continue
        rule: dict[str, Any] = {"color": str(color)}
        if isinstance(col, str) and col:
            rule["col"] = col
        if isinstance(row, int):
            rule["row"] = row
        if isinstance(r.get("predicate"), str) and r["predicate"]:
            rule["predicate"] = r["predicate"]
        out.append(rule)
    return out


def _block_from_response(d: dict[str, Any]) -> Block | None:
    kind = d.get("kind")
    if kind == "kpi_row":
        items: list[KPIItem] = []
        for k in d.get("items", []) or []:
            if not isinstance(k, dict) or not k.get("label") or not k.get("value"):
                continue
            trend = k.get("trend")
            if trend not in ("positive", "negative"):
                trend = None
            items.append(KPIItem(
                label=str(k["label"]), value=str(k["value"]),
                sub=str(k.get("sub") or ""), trend=trend,
            ))
        return KpiRowBlock(block_id=new_block_id(), items=items)
    if kind == "paragraph":
        style = d.get("style", "body")
        if style not in ("body", "lead", "callout-warn", "callout-info"):
            style = "body"
        return ParagraphBlock(
            block_id=new_block_id(),
            text=str(d.get("text", "")),
            style=style,
        )
    if kind == "table":
        return TableBlock(
            block_id=new_block_id(),
            asset_id=str(d["asset_id"]),
            caption=str(d.get("caption", "")),
            highlight_rules=_parse_highlight_rules(d.get("highlight_rules")),
        )
    if kind == "chart":
        return ChartBlock(
            block_id=new_block_id(),
            asset_id=str(d["asset_id"]),
            caption=str(d.get("caption", "")),
        )
    if kind == "chart_table_pair":
        layout = d.get("layout", "h")
        if layout not in ("h", "v"):
            layout = "h"
        return ChartTablePairBlock(
            block_id=new_block_id(),
            chart_asset_id=str(d["chart_asset_id"]),
            table_asset_id=str(d["table_asset_id"]),
            layout=layout,
        )
    if kind == "comparison_grid":
        cols: list[GridColumn] = []
        for c in d.get("columns", []) or []:
            if not isinstance(c, dict) or not c.get("title"):
                continue
            cols.append(GridColumn(
                title=str(c["title"]),
                items=[str(it) for it in c.get("items", []) if it],
            ))
        return ComparisonGridBlock(block_id=new_block_id(), columns=cols)
    if kind == "growth_indicators":
        gr = d.get("growth_rates", {})
        if isinstance(gr, dict):
            return GrowthIndicatorsBlock(
                block_id=new_block_id(),
                growth_rates=gr,
            )
    return None


# ============================================================================
# 辽港数据期刊 PR-1 — 辅助函数 (gated behind USE_KPI_STRIP flag)
# ============================================================================

# PR-2 将此 flag 切为 True；PR-1 阶段默认 False，不影响现有行为。
USE_KPI_STRIP: bool = True
USE_TABLE_TRIM: bool = True


def _trend_to_kpi_strip(
    df: "pd.DataFrame",
    time_col: str,
    value_col: str,
) -> KpiStripBlock:
    """从趋势 DataFrame 自动生成四格 KPI strip。

    固定四格：起点 / 高点 / 当前 / 变化。
    仅当 USE_KPI_STRIP=True 时由 planner 调用。
    """
    import pandas as pd

    if df.empty or time_col not in df.columns or value_col not in df.columns:
        return KpiStripBlock(items=())

    first = df.iloc[0]
    last = df.iloc[-1]
    max_row = df.loc[pd.to_numeric(df[value_col], errors="coerce").idxmax()]

    delta_val = pd.to_numeric(last[value_col], errors="coerce") - pd.to_numeric(
        first[value_col], errors="coerce"
    )

    def _fmt(v) -> str:
        try:
            n = float(v)
            if abs(n) >= 1000:
                return f"{n:,.0f}"
            if abs(n) < 1:
                return f"{n:.2f}"
            return f"{n:.1f}"
        except (ValueError, TypeError):
            return str(v)

    def _delta_fmt(v) -> str:
        try:
            n = float(v)
            absn = abs(n)
            if absn < 1:
                return f"{n:+.2f}"
            return f"{n:+.1f}"
        except (ValueError, TypeError):
            return str(v)

    delta_trend = "gain" if delta_val > 0 else ("loss" if delta_val < 0 else "")
    last_trend = "gain" if delta_val > 0 else ("loss" if delta_val < 0 else "")

    return KpiStripBlock(items=(
        KpiStripItem("起点", _fmt(first[value_col]), str(first[time_col])),
        KpiStripItem("高点", _fmt(max_row[value_col]), str(max_row[time_col])),
        KpiStripItem("当前", _fmt(last[value_col]), str(last[time_col]),
                     trend=last_trend),
        KpiStripItem("变化", _delta_fmt(delta_val), "环比",
                     trend=delta_trend),
    ))


def _trim_table_for_inline(
    df: "pd.DataFrame",
    key_col: str,
    max_rows: int = 5,
) -> tuple["pd.DataFrame", bool]:
    """表格行数截断：超过 max_rows 返回 top-N + 合计行；否则返回原表。

    第二返回值为是否需要折叠（True 表示被截断）。
    """
    if len(df) <= max_rows:
        return df, False

    import pandas as pd

    top = df.nlargest(max_rows, key_col)
    rest_count = len(df) - max_rows
    numeric_cols = df.select_dtypes(include="number").columns
    rest_sum = {}
    for col in df.columns:
        if col in numeric_cols:
            rest_sum[col] = df[col].sum()
        elif col == key_col:
            rest_sum[col] = f"其余 {rest_count} 类合计"
        else:
            rest_sum[col] = ""
    rest_row = pd.DataFrame([rest_sum])
    return pd.concat([top, rest_row], ignore_index=True), True

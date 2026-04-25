"""Descriptive Analysis Skill — computes summary statistics and generates narrative.

Architecture: Planning provides only `intent` + `data_ref`. At execution time:
  1. _column_selector selects target_columns / time_column / group_by from real data.
  2. Statistics are computed on the actual columns.
  3. A single universal LLM narrative prompt (intent-driven, not domain-templated)
     writes 2-3 paragraphs of business insight.
"""
from __future__ import annotations

import json as _json
import logging
from typing import Any

import pandas as pd

from backend.tools._llm import compact_stats_dict, invoke_llm
from backend.tools.analysis._column_selector import select_analysis_columns
from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool

logger = logging.getLogger("analytica.tools.descriptive")

# ── Single universal narrative prompt ─────────────────────────────────────────
# Replaces four hardcoded domain templates (throughput / customer / asset / generic).
# The LLM infers the appropriate analytical angle from `intent` + `col_schema`.

_NARRATIVE_SYSTEM = "你是数据分析专家，擅长从统计数据中提炼业务洞察。"

_NARRATIVE_PROMPT = """【分析意图】
{intent}

【数据列说明】
{col_schema}

【统计概况】
{stats}

【增长率】
{growth}

请写 2-3 段中文业务洞察（每段聚焦一个主题）。

要求：
- 围绕分析意图展开，不要泛泛而谈
- 优先讨论最关键的 2-3 个信号（趋势拐点、同比环比、结构对比、异常值）
- 数字保留 1-2 位小数，大数用万/亿表示
- 如有时间维度，点出变化最显著的时间节点
- 禁止提及：缺失率、标准差、偏度、数据完整性、分布对称性等统计术语
- 不要复述所有数字，提炼核心结论"""


# ── Statistics helpers ─────────────────────────────────────────────────────────

def _shift_month(time_str: str, months: int) -> str | None:
    """Shift a YYYY-MM string by `months` months. Returns None if unparseable."""
    try:
        dt = pd.to_datetime(time_str)
        shifted = dt + pd.DateOffset(months=months)
        return shifted.strftime("%Y-%m") if len(str(time_str).strip()) == 7 else shifted.strftime("%Y-%m-%d")
    except Exception:
        return None


def _compute_summary_stats(
    df: pd.DataFrame,
    target_columns: list[str],
    group_by: str | None = None,
) -> dict:
    stats: dict[str, Any] = {}

    if group_by and group_by in df.columns:
        for group_val, group_df in df.groupby(group_by):
            for col in target_columns:
                if col not in group_df.columns:
                    continue
                series = pd.to_numeric(group_df[col], errors="coerce").dropna()
                key = f"{group_by}_{group_val}"
                stats[str(key)] = {
                    col: {
                        "mean":   round(float(series.mean()),   2) if len(series) > 0 else None,
                        "min":    round(float(series.min()),    2) if len(series) > 0 else None,
                        "max":    round(float(series.max()),    2) if len(series) > 0 else None,
                        "latest": round(float(series.iloc[-1]), 2) if len(series) > 0 else None,
                    }
                }
    else:
        for col in target_columns:
            if col not in df.columns:
                continue
            series = pd.to_numeric(df[col], errors="coerce").dropna()
            stats[col] = {
                "mean":   round(float(series.mean()),   2) if len(series) > 0 else None,
                "min":    round(float(series.min()),    2) if len(series) > 0 else None,
                "max":    round(float(series.max()),    2) if len(series) > 0 else None,
                "latest": round(float(series.iloc[-1]), 2) if len(series) > 0 else None,
            }
    return stats


def _compute_growth_rates_single(
    df: pd.DataFrame,
    target_columns: list[str],
    time_column: str | None,
) -> dict:
    """Compute YoY/MoM for a single-source DataFrame.

    Uses date-string matching (YYYY-MM) for accuracy; falls back to positional
    only when the time column cannot be parsed as a month string.
    """
    growth: dict[str, dict[str, float | None]] = {}

    if not time_column or time_column not in df.columns:
        return {col: {"yoy": None, "mom": None} for col in target_columns}

    df_sorted = df.sort_values(time_column).reset_index(drop=True)
    n = len(df_sorted)
    time_vals = df_sorted[time_column].astype(str)
    latest_time = time_vals.iloc[-1]

    for col in target_columns:
        if col not in df_sorted.columns:
            growth[col] = {"yoy": None, "mom": None}
            continue
        series = pd.to_numeric(df_sorted[col], errors="coerce")
        latest_val = series.iloc[-1]

        if pd.isna(latest_val):
            growth[col] = {"yoy": None, "mom": None}
            continue

        # ── MoM: match the entry exactly 1 month prior ──────────
        mom = None
        mom_time = _shift_month(latest_time, -1)
        if mom_time:
            mask = time_vals == mom_time
            if mask.any():
                prev_val = series[mask].iloc[-1]
                if pd.notna(prev_val) and prev_val != 0:
                    mom = round(float((latest_val - prev_val) / prev_val), 4)
        if mom is None and n >= 2:          # positional fallback
            prev = series.iloc[-2]
            if pd.notna(prev) and prev != 0:
                mom = round(float((latest_val - prev) / prev), 4)

        # ── YoY: match the entry exactly 12 months prior ────────
        yoy = None
        yoy_time = _shift_month(latest_time, -12)
        if yoy_time:
            mask = time_vals == yoy_time
            if mask.any():
                base_val = series[mask].iloc[-1]
                if pd.notna(base_val) and base_val != 0:
                    yoy = round(float((latest_val - base_val) / base_val), 4)
        if yoy is None and n >= 13:         # positional fallback
            base = series.iloc[-13]
            if pd.notna(base) and base != 0:
                yoy = round(float((latest_val - base) / base), 4)

        growth[col] = {"yoy": yoy, "mom": mom}
    return growth


def _compute_growth_rates(
    df: pd.DataFrame,
    target_columns: list[str],
    time_column: str | None,
) -> dict:
    """Dispatch to per-source computation when multiple sources are merged.

    When DataFrames from different tasks are concatenated (e.g. T003 万吨 +
    T004 万箱, both with a ``qty`` column), a ``_src_ref`` marker column is
    present.  Computing growth across the boundary would compare incompatible
    units, so we split by source first.
    """
    if "_src_ref" in df.columns and df["_src_ref"].nunique() > 1:
        combined: dict[str, dict[str, float | None]] = {}
        for src, src_df in df.groupby("_src_ref"):
            src_growth = _compute_growth_rates_single(
                src_df.drop(columns=["_src_ref"]), target_columns, time_column
            )
            for col, rates in src_growth.items():
                if any(v is not None for v in rates.values()):
                    # Prefix with source ref to avoid key collisions
                    combined[f"{src}_{col}"] = rates
        return combined or {col: {"yoy": None, "mom": None} for col in target_columns}

    clean_df = df.drop(columns=["_src_ref"], errors="ignore")
    return _compute_growth_rates_single(clean_df, target_columns, time_column)


# ── Narrative generation ───────────────────────────────────────────────────────

async def _generate_narrative(
    summary_stats: dict,
    growth_rates: dict,
    intent: str,
    col_schema: str,
    *,
    span_emit=None,
    task_id: str = "",
) -> dict[str, Any]:
    trimmed_stats = compact_stats_dict(summary_stats)

    # Filter out all-None growth entries to keep prompt compact
    meaningful_growth = {
        col: rates for col, rates in growth_rates.items()
        if any(v is not None for v in rates.values())
    }

    prompt = _NARRATIVE_PROMPT.format(
        intent=intent or "数据分析",
        col_schema=col_schema or "（无列说明）",
        stats=_json.dumps(trimmed_stats, ensure_ascii=False, default=str),
        growth=_json.dumps(meaningful_growth, ensure_ascii=False, default=str) if meaningful_growth else "（无增长率数据）",
    )

    result = await invoke_llm(
        prompt,
        system_prompt=_NARRATIVE_SYSTEM,
        temperature=0.3,
        timeout=90,
        span_emit=span_emit,
        task_id=task_id,
    )

    if result["error"]:
        return {
            "text": f"[narrative_failed:{result['error_category']}]",
            "tokens": result["tokens"],
            "error_category": result["error_category"],
            "error": result["error"],
        }
    return {
        "text": result["text"],
        "tokens": result["tokens"],
        "error_category": None,
        "error": None,
    }


# ── Skill ──────────────────────────────────────────────────────────────────────

@register_tool(
    "tool_desc_analysis", ToolCategory.ANALYSIS,
    "描述性统计分析（均值、同比、环比、占比）",
    input_spec="data_ref + intent",
    output_spec="统计摘要 JSON（含同比环比增幅）",
)
class DescriptiveAnalysisTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        params = inp.params
        data_ref = params.get("data_ref")
        intent = params.get("intent") or params.get("analysis_goal", "数据分析")
        task_id = params.get("__task_id__", "")

        # Accept Planning-provided overrides but treat them as hints, not mandates
        hint_target_cols: list[str] = params.get("target_columns") or []
        hint_group_by: str | None = params.get("group_by")
        hint_time_col: str | None = params.get("time_column")

        # Normalize LLM-emitted list-for-scalar mistakes
        if isinstance(data_ref, list):
            data_ref = data_ref[0] if data_ref else None
        if isinstance(hint_group_by, list):
            hint_group_by = hint_group_by[0] if hint_group_by else None

        # ── Resolve DataFrame ───────────────────────────────────
        df: pd.DataFrame | None = None
        if data_ref and data_ref in context:
            ctx_output = context[data_ref]
            raw = ctx_output.data if hasattr(ctx_output, "data") else ctx_output
            if isinstance(raw, pd.DataFrame):
                df = raw
        if df is None and inp.context_refs:
            source_dfs: list[tuple[str, pd.DataFrame]] = []
            for ref in inp.context_refs:
                if ref not in context:
                    continue
                raw = context[ref]
                raw = raw.data if hasattr(raw, "data") else raw
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    source_dfs.append((ref, raw))
            if len(source_dfs) == 1:
                df = source_dfs[0][1]
            elif len(source_dfs) > 1:
                # Tag each source so growth-rate computation stays within one
                # series and never compares rows from different metrics/units.
                tagged = []
                for ref, d in source_dfs:
                    d = d.copy()
                    d["_src_ref"] = ref
                    tagged.append(d)
                df = pd.concat(tagged, ignore_index=True)

        if not isinstance(df, pd.DataFrame):
            return self._fail(f"数据引用 {data_ref or inp.context_refs} 不在执行上下文中")
        if df.empty:
            return self._fail("输入数据为空")

        # Sanitize list-type cells
        for col in df.columns:
            if df[col].apply(lambda x: isinstance(x, list)).any():
                df[col] = df[col].astype(str)

        # ── LLM selects columns (always runs; Planning hints as fallback) ──
        # Drop internal marker before exposing schema to LLM
        df_clean = df.drop(columns=["_src_ref"], errors="ignore")
        selection = await select_analysis_columns(
            df_clean, intent, span_emit=inp.span_emit, task_id=task_id,
        )
        target_columns = selection["target_columns"] or [
            c for c in (hint_target_cols or []) if c in df_clean.columns
        ]
        time_column = selection["time_column"] or hint_time_col
        group_by = selection["group_by"] or hint_group_by
        col_schema = selection["col_schema"]

        if not target_columns:
            return self._fail("未找到可分析的数值列")

        # ── Compute statistics ───────────────────────────────────
        # Summary stats use clean df (no cross-source contamination needed)
        summary_stats = _compute_summary_stats(df_clean, target_columns, group_by)
        # Growth rates use tagged df so per-source isolation kicks in
        growth_rates = _compute_growth_rates(df, target_columns, time_column)

        # ── Generate narrative ───────────────────────────────────
        nar = await _generate_narrative(
            summary_stats, growth_rates, intent, col_schema,
            span_emit=inp.span_emit, task_id=task_id,
        )

        status = "partial" if nar["error_category"] else "success"

        return ToolOutput(
            tool_id=self.tool_id,
            status=status,
            output_type="json",
            data={
                "summary_stats": summary_stats,
                "growth_rates": growth_rates,
                "narrative": nar["text"],
            },
            metadata={
                "rows_analyzed": len(df_clean),
                "columns_analyzed": target_columns,
                "group_by": group_by,
                "time_column": time_column,
                "narrative_error_category": nar["error_category"],
            },
            llm_tokens=nar["tokens"],
            error_category=nar["error_category"],
            error_message=nar["error"] if nar["error_category"] else None,
        )

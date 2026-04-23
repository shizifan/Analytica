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

from backend.skills._llm import compact_stats_dict, invoke_llm
from backend.skills.analysis._column_selector import select_analysis_columns
from backend.skills.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.skills.registry import register_skill

logger = logging.getLogger("analytica.skills.descriptive")

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


def _compute_growth_rates(
    df: pd.DataFrame,
    target_columns: list[str],
    time_column: str | None,
) -> dict:
    growth: dict[str, dict[str, float | None]] = {}

    if not time_column or time_column not in df.columns:
        return {col: {"yoy": None, "mom": None} for col in target_columns}

    df_sorted = df.sort_values(time_column).reset_index(drop=True)
    n = len(df_sorted)

    for col in target_columns:
        if col not in df_sorted.columns:
            growth[col] = {"yoy": None, "mom": None}
            continue
        series = pd.to_numeric(df_sorted[col], errors="coerce")

        mom = None
        if n >= 2:
            last, prev = series.iloc[-1], series.iloc[-2]
            if pd.notna(last) and pd.notna(prev) and prev != 0:
                mom = round(float((last - prev) / prev), 4)

        yoy = None
        if n >= 13:
            last, base = series.iloc[-1], series.iloc[-13]
            if pd.notna(last) and pd.notna(base) and base != 0:
                yoy = round(float((last - base) / base), 4)

        growth[col] = {"yoy": yoy, "mom": mom}
    return growth


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

@register_skill(
    "skill_desc_analysis", SkillCategory.ANALYSIS,
    "描述性统计分析（均值、同比、环比、占比）",
    input_spec="data_ref + intent",
    output_spec="统计摘要 JSON（含同比环比增幅）",
)
class DescriptiveAnalysisSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
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
            dfs = []
            for ref in inp.context_refs:
                if ref not in context:
                    continue
                raw = context[ref]
                raw = raw.data if hasattr(raw, "data") else raw
                if isinstance(raw, pd.DataFrame) and not raw.empty:
                    dfs.append(raw)
            if len(dfs) == 1:
                df = dfs[0]
            elif len(dfs) > 1:
                df = pd.concat(dfs, ignore_index=True)

        if not isinstance(df, pd.DataFrame):
            return self._fail(f"数据引用 {data_ref or inp.context_refs} 不在执行上下文中")
        if df.empty:
            return self._fail("输入数据为空")

        # Sanitize list-type cells
        for col in df.columns:
            if df[col].apply(lambda x: isinstance(x, list)).any():
                df[col] = df[col].astype(str)

        # ── LLM selects columns (always runs; Planning hints as fallback) ──
        selection = await select_analysis_columns(
            df, intent, span_emit=inp.span_emit, task_id=task_id,
        )
        target_columns = selection["target_columns"] or [
            c for c in (hint_target_cols or []) if c in df.columns
        ]
        time_column = selection["time_column"] or hint_time_col
        group_by = selection["group_by"] or hint_group_by
        col_schema = selection["col_schema"]

        if not target_columns:
            return self._fail("未找到可分析的数值列")

        # ── Compute statistics ───────────────────────────────────
        summary_stats = _compute_summary_stats(df, target_columns, group_by)
        growth_rates = _compute_growth_rates(df, target_columns, time_column)

        # ── Generate narrative ───────────────────────────────────
        nar = await _generate_narrative(
            summary_stats, growth_rates, intent, col_schema,
            span_emit=inp.span_emit, task_id=task_id,
        )

        status = "partial" if nar["error_category"] else "success"

        return SkillOutput(
            skill_id=self.skill_id,
            status=status,
            output_type="json",
            data={
                "summary_stats": summary_stats,
                "growth_rates": growth_rates,
                "narrative": nar["text"],
            },
            metadata={
                "rows_analyzed": len(df),
                "columns_analyzed": target_columns,
                "group_by": group_by,
                "time_column": time_column,
                "narrative_error_category": nar["error_category"],
            },
            llm_tokens=nar["tokens"],
            error_category=nar["error_category"],
            error_message=nar["error"] if nar["error_category"] else None,
        )

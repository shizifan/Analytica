"""Descriptive Analysis Skill — computes summary statistics and generates narrative.

Uses pandas for statistics and LLM for narrative generation.
Domain-aware prompt selection (throughput / customer / asset / generic) is
driven by ``params._template_meta.template_id`` so narratives focus on the
business signal (完成率 / 同比 / 结构) instead of generic statistics lingo
(缺失率 / 标准差 / 偏度) that dominated pre-batch-3 output.
"""
from __future__ import annotations

import json as _json
import logging
from typing import Any

import pandas as pd

from backend.skills._llm import (
    compact_stats_dict,
    infer_domain,
    invoke_llm,
)
from backend.skills.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.skills.registry import register_skill

logger = logging.getLogger("analytica.skills.descriptive")


def _compute_summary_stats(df: pd.DataFrame, target_columns: list[str], group_by: str | None = None) -> dict:
    """Compute summary statistics for target columns, optionally grouped."""
    stats: dict[str, Any] = {}

    if group_by and group_by in df.columns:
        for group_val, group_df in df.groupby(group_by):
            for col in target_columns:
                if col not in group_df.columns:
                    continue
                series = pd.to_numeric(group_df[col], errors="coerce").dropna()
                key = f"{group_by}_{group_val}" if group_by else col
                stats[str(key)] = {
                    col: {
                        "mean": round(float(series.mean()), 2) if len(series) > 0 else None,
                        "median": round(float(series.median()), 2) if len(series) > 0 else None,
                        "std": round(float(series.std()), 2) if len(series) > 1 else None,
                        "min": round(float(series.min()), 2) if len(series) > 0 else None,
                        "max": round(float(series.max()), 2) if len(series) > 0 else None,
                        "missing_rate": round(float(group_df[col].isna().mean()), 4),
                    }
                }
    else:
        for col in target_columns:
            if col not in df.columns:
                continue
            series = pd.to_numeric(df[col], errors="coerce").dropna()
            stats[col] = {
                "mean": round(float(series.mean()), 2) if len(series) > 0 else None,
                "median": round(float(series.median()), 2) if len(series) > 0 else None,
                "std": round(float(series.std()), 2) if len(series) > 1 else None,
                "min": round(float(series.min()), 2) if len(series) > 0 else None,
                "max": round(float(series.max()), 2) if len(series) > 0 else None,
                "missing_rate": round(float(df[col].isna().mean()), 4),
            }
    return stats


def _compute_growth_rates(
    df: pd.DataFrame, target_columns: list[str], time_column: str | None
) -> dict:
    """Compute YoY and MoM growth rates."""
    growth: dict[str, dict[str, float | None]] = {}

    if not time_column or time_column not in df.columns:
        for col in target_columns:
            growth[col] = {"yoy": None, "mom": None}
        return growth

    df_sorted = df.sort_values(time_column).reset_index(drop=True)
    n = len(df_sorted)

    for col in target_columns:
        if col not in df_sorted.columns:
            growth[col] = {"yoy": None, "mom": None}
            continue

        series = pd.to_numeric(df_sorted[col], errors="coerce")

        # MoM: last vs second-to-last
        mom = None
        if n >= 2:
            last = series.iloc[-1]
            prev = series.iloc[-2]
            if pd.notna(last) and pd.notna(prev) and prev != 0:
                mom = round(float((last - prev) / prev), 4)

        # YoY: last vs 12 months ago
        yoy = None
        if n >= 13:
            last = series.iloc[-1]
            yoy_base = series.iloc[-13]
            if pd.notna(last) and pd.notna(yoy_base) and yoy_base != 0:
                yoy = round(float((last - yoy_base) / yoy_base), 4)

        growth[col] = {"yoy": yoy, "mom": mom}

    return growth


_DOMAIN_PROMPTS: dict[str, str] = {
    "throughput": (
        "你是港口生产运营分析师。基于以下统计数据写 2-3 段业务洞察（中文，每段一个主题）。\n\n"
        "统计概况: {stats}\n"
        "增长率: {growth}\n"
        "分析目标: {goal}\n"
        "聚焦点:\n{focus}\n\n"
        "要求:\n"
        "- 优先讨论: 完成率 / 同比 / 环比 / 板块结构 / 港区对比\n"
        "- 禁止提及: 缺失率、标准差、偏度、数据完整性、分布对称性、异常值检测\n"
        "- 数字保留 1-2 位小数, 大数用万/亿计\n"
        "- 如果数据覆盖多个时段, 点出拐点月份\n"
        "- 不要复述所有数字, 提炼 2-3 个最关键信号\n"
    ),
    "customer": (
        "你是客户战略分析师。基于以下统计数据写 2-3 段业务洞察（中文）。\n\n"
        "统计概况: {stats}\n"
        "增长率: {growth}\n"
        "分析目标: {goal}\n"
        "聚焦点:\n{focus}\n\n"
        "要求:\n"
        "- 优先讨论: 客户结构 / TOP 客户贡献 / 行业分布 / 集中度\n"
        "- 禁止提及: 缺失率、标准差、偏度、数据完整性、分布对称性\n"
        "- 数字保留 1-2 位小数, 大数用万/亿计\n"
        "- 点出最值得关注的 1-2 个客户/行业信号\n"
    ),
    "asset": (
        "你是资产投资分析师。基于以下统计数据写 2-3 段业务洞察（中文）。\n\n"
        "统计概况: {stats}\n"
        "增长率: {growth}\n"
        "分析目标: {goal}\n"
        "聚焦点:\n{focus}\n\n"
        "要求:\n"
        "- 优先讨论: 投资完成率 / 资产周转 / 设备产能利用 / 折旧结构\n"
        "- 禁止提及: 缺失率、标准差、偏度、数据完整性、分布对称性\n"
        "- 数字保留 1-2 位小数\n"
        "- 区分资本性投入与日常运营开销带来的差异\n"
    ),
    "generic": (
        "你是数据分析师，基于以下统计数据写简洁描述性分析（2-3 段, 中文）。\n\n"
        "统计概况: {stats}\n"
        "增长率: {growth}\n"
        "分析背景: {goal}\n"
        "聚焦点:\n{focus}\n\n"
        "要求: 突出最重要的 2-3 个发现, 语言简洁专业, 不要复述所有数字。"
    ),
}


async def _generate_narrative(
    summary_stats: dict,
    growth_rates: dict,
    analysis_goal: str,
    focus_points: list[str],
    template_id: str,
) -> dict[str, Any]:
    """Generate narrative via unified LLM wrapper. Returns dict with
    ``text / tokens / error_category / error``; never raises.
    """
    domain = infer_domain(template_id)
    trimmed_stats = compact_stats_dict(summary_stats)
    focus_block = "\n".join(f"- {p}" for p in focus_points) if focus_points else "（无）"

    prompt = _DOMAIN_PROMPTS[domain].format(
        stats=_json.dumps(trimmed_stats, ensure_ascii=False, default=str),
        growth=_json.dumps(growth_rates, ensure_ascii=False, default=str),
        goal=analysis_goal,
        focus=focus_block,
    )

    result = await invoke_llm(prompt, temperature=0.3, timeout=90)
    if result["error"]:
        # Explicit category tag so upstream (summary_gen) can filter precisely
        # instead of the old opaque "[自动生成失败]".
        return {
            "text": f"[narrative_failed:{result['error_category']}]",
            "tokens": result["tokens"],
            "error_category": result["error_category"],
            "error": result["error"],
            "domain": domain,
        }
    return {
        "text": result["text"],
        "tokens": result["tokens"],
        "error_category": None,
        "error": None,
        "domain": domain,
    }


@register_skill("skill_desc_analysis", SkillCategory.ANALYSIS, "描述性统计分析（均值、同比、环比、占比）",
                input_spec="data_ref + target_columns + group_by + time_column",
                output_spec="统计摘要 JSON（含同比环比增幅）")
class DescriptiveAnalysisSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        params = inp.params
        data_ref = params.get("data_ref")
        target_columns = params.get("target_columns", [])
        group_by = params.get("group_by")
        time_column = params.get("time_column")
        calc_growth = params.get("calc_growth", False)
        analysis_goal = params.get("analysis_goal", "数据分析")
        focus_points = params.get("focus_points", []) or []
        tmpl_meta = params.get("_template_meta", {}) or {}
        template_id = tmpl_meta.get("template_id", "")

        # Normalize: LLM sometimes passes list instead of str
        if isinstance(data_ref, list):
            data_ref = data_ref[0] if data_ref else None
        if isinstance(group_by, list):
            group_by = group_by[0] if group_by else None

        # Get DataFrame from context — fallback to context_refs if data_ref not set
        df = None
        if data_ref and data_ref in context:
            ctx_output = context[data_ref]
            if hasattr(ctx_output, "data"):
                df = ctx_output.data
            elif isinstance(ctx_output, dict):
                df = ctx_output.get("data")
            else:
                df = ctx_output
        elif inp.context_refs:
            # Auto-discover: merge DataFrames from all context_refs
            dfs = []
            for ref in inp.context_refs:
                if ref in context:
                    ctx_output = context[ref]
                    ref_data = ctx_output.data if hasattr(ctx_output, "data") else ctx_output
                    if isinstance(ref_data, pd.DataFrame) and not ref_data.empty:
                        dfs.append(ref_data)
            if len(dfs) == 1:
                df = dfs[0]
            elif len(dfs) > 1:
                df = pd.concat(dfs, ignore_index=True)

        if not isinstance(df, pd.DataFrame):
            return self._fail(f"数据引用 {data_ref or inp.context_refs} 不在执行上下文中")

        if df.empty:
            return self._fail("输入数据为空")

        # Sanitize list-type columns to avoid "unhashable type: 'list'" errors
        for col in df.columns:
            if df[col].apply(lambda x: isinstance(x, list)).any():
                df[col] = df[col].astype(str)

        # Validate and auto-detect target_columns
        if target_columns:
            valid = [c for c in target_columns if c in df.columns]
            target_columns = valid if valid else []

        if not target_columns:
            target_columns = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if not target_columns:
            return self._fail("未找到可分析的数值列")

        # Compute statistics
        summary_stats = _compute_summary_stats(df, target_columns, group_by)

        # Compute growth rates
        growth_rates: dict = {}
        if calc_growth:
            growth_rates = _compute_growth_rates(df, target_columns, time_column)

        # Generate narrative (never raises; returns structured dict)
        nar = await _generate_narrative(
            summary_stats, growth_rates, analysis_goal,
            focus_points, template_id,
        )

        # Partial status when the LLM narrative failed but stats were still
        # computed — lets downstream (_content_collector, summary_gen) decide
        # whether to fall back to stats tables.
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
                "narrative_domain": nar["domain"],
                "narrative_error_category": nar["error_category"],
                "focus_points_count": len(focus_points),
            },
            llm_tokens=nar["tokens"],
            error_category=nar["error_category"],
            error_message=nar["error"] if nar["error_category"] else None,
        )

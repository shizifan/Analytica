"""LLM-powered analysis column selector.

Called by analysis skills AFTER real data is available. The LLM sees actual
column names and sample values, then decides which columns are relevant for
the stated analysis intent.

Entry point: select_analysis_columns(df, intent, span_emit, task_id)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import pandas as pd

from backend.skills._llm import invoke_llm

logger = logging.getLogger("analytica.skills.analysis.column_selector")

_SYSTEM_PROMPT = """你是数据分析专家。根据用户的分析意图和实际数据列信息，决定应该分析哪些列。
严格输出 JSON，不加 markdown 包裹，不加解释文字。"""

_SELECTOR_PROMPT = """【分析意图】{intent}

【实际数据列】
{schema}

请决定本次分析应重点关注的列，输出 JSON：
{{
  "target_columns": ["数值列名1", "数值列名2"],
  "time_column": "时间列名（如果有的话，否则填 null）",
  "group_by": "分组列名（如果需要按某维度分组分析，否则填 null）"
}}

规则：
- target_columns 只选 numeric 类型且与分析意图相关的列（跳过 ID、年份数字等标识列）
- 若分析意图不明确，选所有 numeric 列
- time_column 选 time 类型列（如 dateMonth/monthStr）
- group_by 选最有业务意义的 categorical 分组维度（如港区、货种、客户）"""


_TIME_AXIS_KEYWORDS = ("dateMonth", "monthStr", "monthId", "dateStr", "period",
                       "quarter", "date", "month", "time", "day")

_ID_KEYWORDS = ("id", "code", "no", "num", "index", "seq", "key")


def _col_kind(col: str, dtype) -> str:
    if pd.api.types.is_numeric_dtype(dtype):
        col_lower = col.lower()
        if any(kw in col_lower for kw in _ID_KEYWORDS) and "year" not in col_lower:
            return "id_numeric"
        return "numeric"
    col_lower = col.lower()
    if any(kw.lower() in col_lower for kw in _TIME_AXIS_KEYWORDS):
        return "time"
    return "categorical"


def _describe_schema(df: pd.DataFrame, max_cols: int = 12, sample_rows: int = 2) -> str:
    lines = ["columns:"]
    for col in list(df.columns)[:max_cols]:
        kind = _col_kind(col, df[col].dtype)
        samples = df[col].dropna().head(sample_rows).tolist()
        sample_str = ", ".join(
            f'"{v}"' if isinstance(v, str) else str(round(v, 2)) if isinstance(v, float) else str(v)
            for v in samples
        )
        lines.append(f"  {col} [{kind}]: {sample_str}")
    if len(df.columns) > max_cols:
        lines.append(f"  ... 另有 {len(df.columns) - max_cols} 列")
    lines.append(f"rows_total: {len(df)}")
    return "\n".join(lines)


def _parse_json(text: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text).rstrip("` \n")
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def _fallback_selection(df: pd.DataFrame) -> dict[str, Any]:
    time_cols = [c for c in df.columns if _col_kind(c, df[c].dtype) == "time"]
    numeric_cols = [c for c in df.columns if _col_kind(c, df[c].dtype) == "numeric"]
    cat_cols = [c for c in df.columns if _col_kind(c, df[c].dtype) == "categorical"]
    return {
        "target_columns": numeric_cols,
        "time_column": time_cols[0] if time_cols else None,
        "group_by": None,
    }


async def select_analysis_columns(
    df: pd.DataFrame,
    intent: str,
    *,
    span_emit=None,
    task_id: str = "",
) -> dict[str, Any]:
    """Decide which columns to analyze based on actual DataFrame schema and intent.

    Returns dict with:
        target_columns: list[str] — numeric columns to compute stats on
        time_column: str | None  — time axis column for growth rate calc
        group_by: str | None     — grouping dimension (e.g. portArea, cargoType)

    Always returns valid selection — falls back to all numeric cols on failure.
    """
    if df is None or df.empty:
        return {"target_columns": [], "time_column": None, "group_by": None}

    schema = _describe_schema(df)
    user_prompt = _SELECTOR_PROMPT.format(intent=intent or "数据分析", schema=schema)

    result = await invoke_llm(
        user_prompt,
        system_prompt=_SYSTEM_PROMPT,
        temperature=0.1,
        timeout=20,
        max_prompt_chars=2500,
        span_emit=span_emit,
        task_id=task_id,
    )

    if result.get("error"):
        logger.warning("column selector LLM failed [%s]: %s — using fallback",
                       result.get("error_category"), result.get("error"))
        return _fallback_selection(df)

    parsed = _parse_json(result["text"])
    if parsed is None:
        logger.warning("column selector: JSON parse failed, text=%r", result["text"][:200])
        return _fallback_selection(df)

    # Validate: filter to columns actually in df
    cols = set(df.columns)
    target = [c for c in (parsed.get("target_columns") or []) if c in cols]
    time_col = parsed.get("time_column")
    group_by = parsed.get("group_by")

    if not target:
        target = [c for c in df.columns if _col_kind(c, df[c].dtype) == "numeric"]
    if time_col and time_col not in cols:
        time_col = None
    if group_by and group_by not in cols:
        group_by = None

    logger.info("column selector OK: target=%s time=%s group=%s", target, time_col, group_by)
    return {"target_columns": target, "time_column": time_col, "group_by": group_by}

"""LLM-powered chart column mapper.

Called by visualization skills AFTER real data is available. The LLM sees
actual column names and sample rows, then decides the axis/series mapping.
This replaces the Planning-phase guesswork (x_field, y_fields, series_by)
that was baked into task params without ever seeing the data.

Entry point: decide_chart_mapping(df, intent, chart_type, span_emit, task_id)
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from backend.config import get_settings
from backend.tools._llm import extract_json, invoke_llm

logger = logging.getLogger("analytica.tools.visualization.llm_mapper")

# ── DataFrame summary for LLM ────────────────────────────────────

# Strict date-axis keywords: must look like a timeline x-axis, not just "year"
# currYear/preYear are grouping dimensions → categorical, not time axis
_TIME_AXIS_KEYWORDS = ("dateMonth", "monthStr", "monthId", "dateStr", "period",
                       "quarter", "date", "month", "time", "day")


def _col_kind(col: str, dtype) -> str:
    """Classify a column as time / numeric / categorical for the LLM prompt.

    "time" means it is a time-axis column (e.g. dateMonth="2026-01").
    Columns like currYear / preYear are grouping dimensions → categorical.
    """
    if pd.api.types.is_numeric_dtype(dtype):
        return "numeric"
    col_lower = col.lower()
    if any(kw.lower() in col_lower for kw in _TIME_AXIS_KEYWORDS):
        return "time"
    return "categorical"


def describe_dataframe(df: pd.DataFrame, max_cols: int = 10, sample_rows: int = 2) -> str:
    """Produce a compact schema + sample description for the LLM prompt.

    Output example:
        columns:
          dateMonth [time]: "2026-01", "2026-02"
          qty [numeric]: 3215.4, 2980.1
          currYear [categorical]: "2026", "2025"
        rows_total: 16
    """
    lines = ["columns:"]
    cols = list(df.columns)[:max_cols]
    for col in cols:
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


# ── Per-chart-type prompts ───────────────────────────────────────

_SYSTEM_PROMPT = """你是图表配置专家。根据用户意图和实际数据列信息，决定图表的轴映射配置。
严格输出 JSON，不加 markdown 包裹，不加解释文字。"""

_LINE_PROMPT = """【用户意图】{intent}

【实际数据】
{schema}

请决定折线图的配置，输出 JSON：
{{
  "x_field": "时间轴列名（必须是 time 类型列）",
  "y_fields": ["数值列名1", "数值列名2（如有多条线）"],
  "series_by": "分组列名（如需按年份/类别分多条线，否则填 null）",
  "title": "简洁中文图表标题（15字以内）",
  "y_axis_label": "Y轴单位描述（如"万吨"，可为空字符串）"
}}

规则：
- x_field 必须选 time 类型列
- y_fields 只选有分析价值的 numeric 列（跳过 ID、年份数字等标识列）
- 若 categorical 列值只有 2-3 个不同值（如年份），用 series_by 分多条线，此时 y_fields 只需1列
- series_by 与 y_fields 不能是同一列"""

_BAR_PROMPT = """【用户意图】{intent}

【实际数据】
{schema}

请决定柱状图的配置，输出 JSON：
{{
  "x_field": "类别轴列名（categorical 或 time 类型）",
  "y_fields": ["数值列名1"],
  "series_by": "分组列名（需要分组对比时填，否则 null）",
  "title": "简洁中文图表标题（15字以内）",
  "sort": "desc（按值降序）或 null（保持原序）",
  "orientation": "vertical（竖向）或 horizontal（横向，类别名长时用）"
}}

规则：
- x_field 优先选 categorical 类型列（名称/类型维度）
- y_fields 选最能体现用户意图的数值列，通常1列
- 类别名称较长（>4字）时用 horizontal"""

_WATERFALL_PROMPT = """【用户意图】{intent}

【实际数据】
{schema}

请决定瀑布图的配置，输出 JSON：
{{
  "category_field": "类别列名（每个条目的名称）",
  "value_field": "数值列名（变化量，可正可负）",
  "title": "简洁中文图表标题（15字以内）"
}}

规则：
- value_field 选表示增减变化的 numeric 列（同比变化量、差值等）
- category_field 选 categorical 列（港区名、业务类型等）"""

_PROMPTS = {
    "line": _LINE_PROMPT,
    "bar": _BAR_PROMPT,
    "waterfall": _WATERFALL_PROMPT,
}

# ── Expected output keys per chart type ──────────────────────────

_REQUIRED_KEYS: dict[str, list[str]] = {
    "line":      ["x_field", "y_fields", "title"],
    "bar":       ["x_field", "y_fields", "title"],
    "waterfall": ["category_field", "value_field", "title"],
}


# ── Rule-based fallback ──────────────────────────────────────────

def _fallback_mapping(df: pd.DataFrame, chart_type: str, intent: str) -> dict[str, Any]:
    """Rule-based column mapping used when LLM call fails or returns invalid JSON."""
    cols = list(df.columns)
    time_cols = [c for c in cols if any(kw.lower() in c.lower() for kw in _TIME_AXIS_KEYWORDS)
                 and not pd.api.types.is_numeric_dtype(df[c])]
    num_cols = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    cat_cols = [c for c in cols if not pd.api.types.is_numeric_dtype(df[c]) and c not in time_cols]

    if chart_type == "line":
        x = time_cols[0] if time_cols else (cat_cols[0] if cat_cols else cols[0])
        y = [c for c in num_cols if c != x][:2] or num_cols[:1]
        return {"x_field": x, "y_fields": y, "series_by": None, "title": intent[:15], "y_axis_label": ""}

    if chart_type == "bar":
        x = cat_cols[0] if cat_cols else (time_cols[0] if time_cols else cols[0])
        y = num_cols[:1]
        return {"x_field": x, "y_fields": y, "series_by": None, "title": intent[:15],
                "sort": None, "orientation": "vertical"}

    # waterfall
    cat = cat_cols[0] if cat_cols else cols[0]
    val = num_cols[0] if num_cols else (cols[1] if len(cols) > 1 else cols[0])
    return {"category_field": cat, "value_field": val, "title": intent[:15]}




def _validate_mapping(mapping: dict, df: pd.DataFrame, chart_type: str) -> bool:
    """Check that required keys exist and referenced columns are in the DataFrame."""
    for key in _REQUIRED_KEYS.get(chart_type, []):
        if key not in mapping:
            return False
    cols = set(df.columns)
    if chart_type in ("line", "bar"):
        if mapping.get("x_field") not in cols:
            return False
        y_fields = mapping.get("y_fields") or []
        if not y_fields or not all(f in cols for f in y_fields):
            return False
    elif chart_type == "waterfall":
        if mapping.get("category_field") not in cols:
            return False
        if mapping.get("value_field") not in cols:
            return False
    return True


# ── Hint extraction from fetch-task metadata ────────────────────

def _extract_display_hint_from_context(
    context: dict[str, Any],
    chart_type: str,
    df: pd.DataFrame,
) -> dict[str, Any] | None:
    """Check upstream data_fetch ToolOutputs for a matching display_hint.

    api_fetch stores a display_hint in metadata when it resolves params with
    LLM. If that hint names valid columns for the requested chart type, reuse
    it instead of making another LLM call.
    """
    for out in context.values():
        hint = (getattr(out, "metadata", None) or {}).get("display_hint")
        if not isinstance(hint, dict):
            continue
        if hint.get("type") == "chart" or chart_type in ("line", "bar", "waterfall"):
            if chart_type in ("line", "bar"):
                x = hint.get("x_field")
                y = hint.get("y_field") or hint.get("y_fields")
                if isinstance(y, str):
                    y = [y]
                if x and y and x in df.columns and all(f in df.columns for f in y):
                    return {
                        "x_field": x,
                        "y_fields": y,
                        "series_by": hint.get("series_by"),
                        "title": hint.get("title") or "",
                        "y_axis_label": hint.get("y_axis_label") or "",
                        "sort": hint.get("sort"),
                        "orientation": hint.get("orientation", "vertical"),
                    }
            elif chart_type == "waterfall":
                cat = hint.get("x_field") or hint.get("category_field")
                val = hint.get("y_field") or hint.get("value_field")
                if cat and val and cat in df.columns and val in df.columns:
                    return {"category_field": cat, "value_field": val, "title": hint.get("title") or ""}
    return None


# ── Public entry point ───────────────────────────────────────────

async def decide_chart_mapping(
    df: pd.DataFrame,
    intent: str,
    chart_type: str,
    *,
    span_emit=None,
    task_id: str = "",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide axis/series mapping for a chart based on actual DataFrame columns.

    Always returns a valid mapping dict — falls back to rule-based detection
    if the LLM call fails or returns an unusable response.

    Args:
        df:         Actual DataFrame from upstream data_fetch task.
        intent:     Human-readable description of what the chart should show
                    (from task.name or task.description).
        chart_type: "line" | "bar" | "waterfall"
        span_emit:  Async callable for tracing (passed to invoke_llm).
        task_id:    Task ID for tracing correlation.
    """
    if df is None or df.empty:
        return _fallback_mapping(pd.DataFrame(), chart_type, intent)

    # Reuse display_hint from upstream api_fetch if it names valid columns —
    # avoids a redundant LLM call when param resolution already produced a hint.
    if context:
        cached = _extract_display_hint_from_context(context, chart_type, df)
        if cached:
            logger.info("chart mapping: reusing display_hint from fetch metadata [%s]", chart_type)
            return cached

    prompt_template = _PROMPTS.get(chart_type, _LINE_PROMPT)
    schema = describe_dataframe(df)
    user_prompt = prompt_template.format(intent=intent or "图表展示", schema=schema)

    result = await invoke_llm(
        user_prompt,
        system_prompt=_SYSTEM_PROMPT,
        temperature=get_settings().LLM_TEMPERATURE_DEFAULT,
        timeout=30,
        max_prompt_chars=3000,
        span_emit=span_emit,
        task_id=task_id,
    )

    if result.get("error"):
        logger.warning(
            "chart mapping LLM failed [%s]: %s — using rule-based fallback",
            result.get("error_category"), result.get("error"),
        )
        return _fallback_mapping(df, chart_type, intent)

    mapping = extract_json(result["text"])
    if mapping is None:
        logger.warning("chart mapping: JSON parse failed, text=%r", result["text"][:200])
        return _fallback_mapping(df, chart_type, intent)

    if not _validate_mapping(mapping, df, chart_type):
        logger.warning(
            "chart mapping: validation failed (cols not in df), mapping=%s, df_cols=%s",
            mapping, list(df.columns),
        )
        return _fallback_mapping(df, chart_type, intent)

    logger.info("chart mapping OK [%s]: %s", chart_type, {k: v for k, v in mapping.items() if k != "title"})
    return mapping

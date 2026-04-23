"""Multi-source data summarizer for analysis skills.

Produces compact, LLM-readable summaries of one or more upstream DataFrames.
Used by attribution.py (and future anomaly/prediction skills) to give the LLM
a structured view of real data without dumping raw JSON.

Each data source becomes a short block like:

  [T001] 4行 × 2列
    dateMonth [time]: 2026-01 → 2026-04
    num [numeric]: 最小=541, 均值=942, 最大=1376, 最新=541

Total budget: ~500 chars per source, capped at MAX_SOURCES sources.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger("analytica.tools.analysis.data_summarizer")

MAX_SOURCES = 8
MAX_COLS_PER_SOURCE = 10
MAX_CAT_VALUES = 5        # show at most N distinct values for categorical cols

_TIME_KEYWORDS = ("dateMonth", "monthStr", "monthId", "dateStr", "period",
                  "quarter", "date", "month", "time", "day")
_ID_KEYWORDS = ("id", "code", "no", "index", "seq", "key")


def _col_kind(col: str, dtype) -> str:
    if pd.api.types.is_numeric_dtype(dtype):
        col_lower = col.lower()
        if any(kw in col_lower for kw in _ID_KEYWORDS) and "year" not in col_lower:
            return "id"
        return "numeric"
    col_lower = col.lower()
    if any(kw.lower() in col_lower for kw in _TIME_KEYWORDS):
        return "time"
    return "categorical"


def _summarize_df(ref: str, df: pd.DataFrame) -> str:
    """Produce a compact text summary of one DataFrame."""
    cols = list(df.columns)[:MAX_COLS_PER_SOURCE]
    n_rows, n_cols = len(df), len(df.columns)
    lines = [f"[{ref}] {n_rows}行 × {n_cols}列"]

    for col in cols:
        kind = _col_kind(col, df[col].dtype)
        series = df[col].dropna()

        if kind == "time":
            vals = series.astype(str).tolist()
            if vals:
                span = f"{vals[0]} → {vals[-1]}" if len(vals) > 1 else vals[0]
                lines.append(f"  {col} [time]: {span}")

        elif kind == "numeric":
            num = pd.to_numeric(series, errors="coerce").dropna()
            if len(num) == 0:
                continue
            mn   = round(float(num.min()),  2)
            mx   = round(float(num.max()),  2)
            mean = round(float(num.mean()), 2)
            latest = round(float(num.iloc[-1]), 2)
            lines.append(
                f"  {col} [numeric]: 最小={mn}, 均值={mean}, 最大={mx}, 最新={latest}"
            )

        elif kind == "categorical":
            uniq = series.astype(str).unique().tolist()
            if len(uniq) <= MAX_CAT_VALUES:
                val_str = " / ".join(uniq)
            else:
                val_str = " / ".join(uniq[:MAX_CAT_VALUES]) + f" … (共{len(uniq)}种)"
            lines.append(f"  {col} [categorical]: {val_str}")

        # skip id columns

    if len(df.columns) > MAX_COLS_PER_SOURCE:
        lines.append(f"  … 另有 {len(df.columns) - MAX_COLS_PER_SOURCE} 列未展示")

    return "\n".join(lines)


def _extract_df(ctx_output: Any) -> pd.DataFrame | None:
    """Pull a DataFrame out of a SkillOutput or raw value."""
    if hasattr(ctx_output, "data"):
        val = ctx_output.data
    elif isinstance(ctx_output, dict):
        val = ctx_output.get("data")
    else:
        val = ctx_output

    if isinstance(val, pd.DataFrame) and not val.empty:
        return val

    # Attribution skills also produce dict outputs with nested stats —
    # these aren't DataFrames, so skip gracefully.
    return None


def summarize_sources(
    context: dict[str, Any],
    refs: list[str],
    *,
    max_sources: int = MAX_SOURCES,
) -> str:
    """Summarize all upstream task outputs referenced by `refs`.

    Returns a multi-block text string ready to embed in a prompt.
    Non-DataFrame outputs (e.g. prior analysis results as dicts) are
    included as compact JSON snippets instead of table summaries.
    """
    blocks: list[str] = []

    for ref in refs[:max_sources]:
        if ref not in context:
            continue
        ctx_out = context[ref]
        df = _extract_df(ctx_out)

        if df is not None:
            blocks.append(_summarize_df(ref, df))
        else:
            # Non-DataFrame output (analysis result, attribution, etc.)
            raw = ctx_out.data if hasattr(ctx_out, "data") else ctx_out
            if raw is None:
                continue
            try:
                import json
                snippet = json.dumps(raw, ensure_ascii=False, default=str)
                if len(snippet) > 800:
                    snippet = snippet[:800] + "…（截断）"
                blocks.append(f"[{ref}] (分析结果)\n  {snippet}")
            except Exception:
                blocks.append(f"[{ref}] (无法序列化)")

    if not blocks:
        return "（无可用数据）"
    return "\n\n".join(blocks)

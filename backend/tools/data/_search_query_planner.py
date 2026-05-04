"""LLM-powered search query planner — produces 1-3 search-engine-optimised
queries from a user's analytical question with layered context.

Responsibilities:
- plan_search_queries  — before the provider call, use LLM to decompose the
  user's analytical intent into 1-3 keyword-heavy queries (multi-angle:
  facts / stats / policy / comparison), each ≤ 12 chars.

Pattern: same as ``_param_resolver.py`` (LLM-in-tool, dedicated semaphore,
graceful fallback on failure). The old ``_optimize_search_query`` in
``web_search.py`` is deprecated in favour of this planner.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from backend.config import get_settings
from backend.tools._llm import extract_json, invoke_llm

logger = logging.getLogger("analytica.tools.search_query_planner")

# Dedicated semaphore for the search query planner. Limit of 3 is ample
# because only one search task is scheduled per plan, and the planner
# calls are short (prompt ~1 KB, output ~200 chars).
_PLANNER_SEMAPHORE: asyncio.Semaphore | None = None
_PLANNER_LIMIT = 3


def _get_planner_semaphore() -> asyncio.Semaphore:
    global _PLANNER_SEMAPHORE
    if _PLANNER_SEMAPHORE is None:
        _PLANNER_SEMAPHORE = asyncio.Semaphore(_PLANNER_LIMIT)
    return _PLANNER_SEMAPHORE


# ── Constants ──────────────────────────────────────────────────

_LIAGANG_BACKGROUND = (
    "辽港集团（辽宁港口集团），主要港口包括大连港、营口港、盘锦港等，"
    "业务涵盖集装箱、散杂货、油化品、商品车、滚装等货类。"
)

_SYSTEM_PROMPT = (
    "你是互联网搜索规划专家，负责为数据分析任务规划检索词。"
    "只输出纯 JSON，不输出任何 markdown 包裹或解释文字。"
)

_USER_PROMPT_TEMPLATE = """\
【必备背景】
- 公司：{liagang_background}
- 用户问题：{raw_query}
- 任务意图：{task_purpose}
- 今天日期：{today}

【可选背景：员工领域知识】
{public_hint_block}

【输出要求】
为本次搜索产出 1~3 条互联网检索词，要求：
- 每条 ≤ 12 字/词，名词短语优先，避免疑问句
- 第一条必须是"最高召回"的组合（最通用的关键词）
- 多角度（事实 / 统计数字 / 政策 / 对比）至多 3 条
- 输出 JSON 格式：
  {{"queries": ["关键词组合1", "关键词组合2"], "rationale": "选择理由", "stop_when": "满足条件即可停止搜索"}}
"""

# ── Public API ─────────────────────────────────────────────────


async def plan_search_queries(
    raw_query: str,
    *,
    domain_context: str = "",
    public_hint: str = "",
    task_purpose: str = "",
    span_emit: Any = None,
    task_id: str = "",
) -> dict[str, Any]:
    """Decompose the user's analytical question into 1-3 keyword queries.

    Parameters
    ----------
    raw_query : str
        The original user question / search intent.
    domain_context : str
        Company / scope keyword (e.g. "辽港集团").
    public_hint : str
        Optional employee-level public keyword hints (e.g. "港口设备、资产管理").
    task_purpose : str
        Brief description of what the analysis task is trying to achieve.
    span_emit : callable or None
        Tracing span emitter.
    task_id : str
        Correlation id for tracing.

    Returns
    -------
    dict with keys:
        queries : list[str]      — 1-3 keyword queries (≥ 1 always)
        rationale : str          — why these queries were chosen
        stop_when : str         — when to stop searching
    Falls back to ``{"queries": [raw_query], "rationale": "", "stop_when": ""}``
    on any LLM failure (match _param_resolver best-effort contract).
    """
    if not raw_query:
        return {"queries": [], "rationale": "", "stop_when": ""}

    # Build the optional-block line
    hint_text = public_hint.strip() if public_hint else "（未配置，按通用方式处理）"

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        liagang_background=_LIAGANG_BACKGROUND,
        raw_query=raw_query,
        task_purpose=task_purpose or "数据分析",
        today=date.today().isoformat(),
        public_hint_block=hint_text,
    )

    settings = get_settings()
    temperature = getattr(settings, "LLM_TEMPERATURE_BALANCED", 0.2)

    try:
        result = await invoke_llm(
            user_prompt,
            system_prompt=_SYSTEM_PROMPT,
            temperature=temperature,
            timeout=20,
            max_prompt_chars=3000,
            span_emit=span_emit,
            task_id=task_id,
            _semaphore=_get_planner_semaphore(),
        )
    except Exception:
        logger.warning(
            "Query planner LLM call failed for task %s, falling back to raw_query",
            task_id,
        )
        return _fallback(raw_query)

    if result.get("error"):
        logger.warning(
            "Query planner returned error for task %s: %s, falling back",
            task_id, result["error"],
        )
        return _fallback(raw_query)

    text = result.get("text", "")
    parsed = extract_json(text)
    if parsed is None:
        logger.warning(
            "Query planner produced unparseable output for task %s: %r, falling back",
            task_id, text[:200],
        )
        return _fallback(raw_query)

    queries = parsed.get("queries")
    if not isinstance(queries, list) or len(queries) == 0:
        logger.warning(
            "Query planner returned empty/missing queries for task %s: %r, falling back",
            task_id, parsed,
        )
        return _fallback(raw_query)

    # Validate each query is a non-empty string
    valid_queries = [str(q).strip() for q in queries if q and str(q).strip()]
    if not valid_queries:
        return _fallback(raw_query)

    rationale = str(parsed.get("rationale", ""))
    stop_when = str(parsed.get("stop_when", ""))

    logger.info(
        "Query planner produced %d queries for task %s: %s",
        len(valid_queries), task_id, valid_queries,
    )

    return {
        "queries": valid_queries,
        "rationale": rationale,
        "stop_when": stop_when,
    }


# ── Internal helpers ───────────────────────────────────────────


def _fallback(raw_query: str) -> dict[str, Any]:
    """Best-effort fallback: return the raw query as a single-item list."""
    return {
        "queries": [raw_query],
        "rationale": "降级回退（LLM 规划失败）",
        "stop_when": "",
    }

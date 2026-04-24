"""LLM-powered parameter resolution for the API fetch skill.

Two responsibilities:
1. resolve_params_with_llm  — before the first API call, use LLM to clean
   the planner's params against the endpoint spec and infer a display hint.
2. diagnose_and_fix_params  — after an empty-result or business-error, use
   LLM to suggest corrected params for the next retry attempt.

Both functions are best-effort: they fall back gracefully if the LLM call
fails or returns unparseable JSON.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from backend.tools._llm import extract_json, invoke_llm

logger = logging.getLogger("analytica.tools.param_resolver")

# Dedicated semaphore for lightweight structured-output LLM calls made during
# data_fetch. Higher limit than the global analysis semaphore (2) because:
#   - prompts are short (~1-2 KB vs 8 KB for analysis)
#   - output tokens are tiny (a small JSON dict)
#   - up to 8 data_fetch tasks may run concurrently and all need param resolution
# Using the global semaphore (limit=2) would serialize 8 tasks into 4 batches,
# adding ~30-40s of queuing before even a single API call is made.
_RESOLVER_SEMAPHORE: asyncio.Semaphore | None = None
_RESOLVER_LIMIT = 5


def _get_resolver_semaphore() -> asyncio.Semaphore:
    global _RESOLVER_SEMAPHORE
    if _RESOLVER_SEMAPHORE is None:
        _RESOLVER_SEMAPHORE = asyncio.Semaphore(_RESOLVER_LIMIT)
    return _RESOLVER_SEMAPHORE

# Maximum inner retries within a single api_fetch execution.
# This value is read by api_fetch.py as the source of truth.
MAX_FETCH_RETRIES: int = 3

# ── Prompt templates ──────────────────────────────────────────

_RESOLVE_SYSTEM = (
    "你是 API 参数专家，根据端点规范分析并清洗传入参数，同时给出展示建议。"
    "只输出纯 JSON，不输出任何 markdown 包裹或解释文字。"
)

_RESOLVE_PROMPT = """\
## API 端点：{name}
意图：{intent}
必填参数：{required}
可选参数：{optional}
参数说明：{param_note}
返回字段：{returns}
注意事项：{analysis_note}

## 计划传入的参数（来自规划层）：
{planned_params}

## 任务描述：
{task_context}

请输出：
1. resolved — 最终应传入 API 的参数（必填参数必须保留；可选参数按需；不合理的值须修正或删除）
2. display_hint — 建议展示方式（type: "table" 或 "chart"；chart_type: "line"/"bar"/"pie"/null；x_field/y_field: 字段名）

输出纯 JSON，示例格式（字段名不要翻译）：
{{"resolved": {{"param1": "val"}}, "display_hint": {{"type": "chart", "chart_type": "line", "x_field": "dateMonth", "y_field": "qty"}}}}"""

_DIAGNOSE_SYSTEM = (
    "你是 API 调试专家，分析 API 调用失败或返回空数据的原因，输出修正后的参数。"
    "只输出纯 JSON，不输出任何说明文字。"
)

_DIAGNOSE_PROMPT = """\
## API 端点：{name}
意图：{intent}
参数说明：{param_note}
注意事项：{analysis_note}

## 第 {attempt} 次尝试使用的参数：
{params}

## 问题描述：
{error_info}

分析失败原因，给出修正后的参数。若确实无法修复则输出 null。

【重要约束】
- 若问题是"返回空数据"，禁止修改任何时间参数（date/startDate/endDate/dateMonth/dateYear/currYear 等）。时间参数由用户明确指定，空数据代表该时段确实无数据，应输出 null。
- 只有当错误明确是参数格式错误（如类型不匹配、枚举值非法）时，才允许修正对应参数，且不得改变参数的语义含义（如把某月改成另一年）。

输出纯 JSON：{{"fixed": {{...}} 或 null, "reason": "简要说明"}}"""


# ── Public API ─────────────────────────────────────────────────

async def resolve_params_with_llm(
    endpoint: Any,
    planned_params: dict[str, Any],
    task_context: str = "",
    span_emit: Any = None,
    task_id: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Analyze endpoint spec + planned params with LLM → (resolved_params, display_hint).

    Falls back to planned_params unchanged when the LLM call fails or returns
    invalid JSON.  Never raises.
    """
    field_schema = endpoint.field_schema or ()
    returns_str = endpoint.returns or ""
    if field_schema:
        fields = ", ".join(f"{n}({t})" for n, t, *_ in field_schema)
        returns_str = f"{returns_str} | 字段: {fields}"

    prompt = _RESOLVE_PROMPT.format(
        name=endpoint.name,
        intent=endpoint.intent,
        required=", ".join(endpoint.required) or "（无）",
        optional=", ".join(endpoint.optional) or "（无）",
        param_note=endpoint.param_note or "（无）",
        returns=returns_str,
        analysis_note=endpoint.analysis_note or "（无）",
        planned_params=json.dumps(planned_params, ensure_ascii=False, indent=2),
        task_context=task_context[:400] or "（未提供）",
    )

    result = await invoke_llm(
        prompt,
        system_prompt=_RESOLVE_SYSTEM,
        temperature=0.1,
        timeout=30,
        max_prompt_chars=3000,
        span_emit=span_emit,
        task_id=task_id,
        _semaphore=_get_resolver_semaphore(),
    )

    if result["error"]:
        logger.warning(
            "[param_resolver] resolve failed for %s: %s", endpoint.name, result["error"]
        )
        return planned_params, {}

    parsed = extract_json(result["text"])
    if not parsed:
        logger.warning(
            "[param_resolver] resolve: unparseable JSON from LLM for %s: %.200s",
            endpoint.name, result["text"],
        )
        return planned_params, {}

    resolved: dict[str, Any] = parsed.get("resolved") or {}
    display_hint: dict[str, Any] = parsed.get("display_hint") or {}

    if not isinstance(resolved, dict) or not resolved:
        logger.warning(
            "[param_resolver] resolve: empty resolved dict for %s, using planned params",
            endpoint.name,
        )
        return planned_params, display_hint

    # Strip internal keys that must never reach the real API
    resolved.pop("endpoint_id", None)
    resolved.pop("__task_id__", None)
    resolved.pop("__task_name__", None)

    logger.info(
        "[param_resolver] %s: planned=%s → resolved=%s",
        endpoint.name, planned_params, resolved,
    )
    return resolved, display_hint


async def diagnose_and_fix_params(
    endpoint: Any,
    params: dict[str, Any],
    error_info: str,
    attempt: int,
    span_emit: Any = None,
    task_id: str = "",
) -> dict[str, Any] | None:
    """Ask LLM to diagnose an error/empty result and suggest fixed params.

    Returns a corrected params dict, or None if the LLM cannot fix it.
    Never raises.
    """
    prompt = _DIAGNOSE_PROMPT.format(
        name=endpoint.name,
        intent=endpoint.intent,
        param_note=endpoint.param_note or "（无）",
        analysis_note=endpoint.analysis_note or "（无）",
        attempt=attempt,
        params=json.dumps(params, ensure_ascii=False, indent=2),
        error_info=error_info[:500],
    )

    result = await invoke_llm(
        prompt,
        system_prompt=_DIAGNOSE_SYSTEM,
        temperature=0.1,
        timeout=30,
        max_prompt_chars=2000,
        span_emit=span_emit,
        task_id=task_id,
        _semaphore=_get_resolver_semaphore(),
    )

    if result["error"]:
        logger.warning(
            "[param_resolver] diagnose failed for %s (attempt=%d): %s",
            endpoint.name, attempt, result["error"],
        )
        return None

    parsed = extract_json(result["text"])
    if not parsed:
        return None

    fixed: dict[str, Any] | None = parsed.get("fixed")
    reason: str = parsed.get("reason", "")

    if not isinstance(fixed, dict) or not fixed:
        logger.info(
            "[param_resolver] diagnose: LLM says unfixable for %s (attempt=%d): %s",
            endpoint.name, attempt, reason,
        )
        return None

    fixed.pop("endpoint_id", None)
    fixed.pop("__task_id__", None)
    fixed.pop("__task_name__", None)

    logger.info(
        "[param_resolver] %s attempt=%d fix: %s → %s (reason: %s)",
        endpoint.name, attempt, params, fixed, reason,
    )
    return fixed

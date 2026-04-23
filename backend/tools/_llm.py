"""Unified LLM invocation helper for analysis/report skills.

Provides a single ``invoke_llm`` coroutine that wraps ChatOpenAI with:
- a process-global semaphore (caps concurrent LLM calls across skills)
- prompt truncation (protects against 400 context_length errors)
- unified exception classification (uses ErrorCategory from skills.base)
- token usage extraction

This replaces the duplicated ``try ChatOpenAI.ainvoke except Exception``
pattern in descriptive.py / summary_gen.py / attribution.py. Each skill
used to swallow all failures into a single fallback string like
"[自动生成失败] ..." — that made root-cause invisible. Now callers get a
structured dict with ``error_category`` that observability can aggregate.

NOTE: the retry loop sits one layer higher (in execute_plan's
_execute_single_task). This helper performs a single attempt so it doesn't
double-retry on rate limits.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Awaitable, Callable

from backend.tools.base import ErrorCategory, classify_exception
from backend.tracing import make_span

logger = logging.getLogger("analytica.tools.llm")

# Process-global concurrency cap. Separate from execution.py's per-task-type
# semaphore because a single "analysis" task may internally issue multiple
# LLM calls (system + user prompts, retries). This is the upper bound across
# all concurrent LLM activity in the process.
#
# Initialized lazily on first use to bind to the active event loop.
_GLOBAL_LLM_SEMAPHORE: asyncio.Semaphore | None = None
_GLOBAL_LLM_LIMIT = 2


def _get_semaphore() -> asyncio.Semaphore:
    global _GLOBAL_LLM_SEMAPHORE
    if _GLOBAL_LLM_SEMAPHORE is None:
        _GLOBAL_LLM_SEMAPHORE = asyncio.Semaphore(_GLOBAL_LLM_LIMIT)
    return _GLOBAL_LLM_SEMAPHORE


def _reset_semaphore() -> None:
    """Called between event loops (e.g. pytest parametrized async tests)."""
    global _GLOBAL_LLM_SEMAPHORE
    _GLOBAL_LLM_SEMAPHORE = None


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks (Qwen reasoning traces)."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def truncate(text: str, max_chars: int = 8000) -> str:
    """Truncate a prompt component, leaving an explicit marker."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n...[截断 {len(text) - max_chars} 字符]"


def _extract_usage(response: Any) -> dict[str, int]:
    """Extract {"prompt": int, "completion": int} from a LangChain response.

    Different providers / LangChain versions put token counts in different
    places. Probe the likely attribute paths and fall back to an empty dict.
    """
    # 1) response_metadata.token_usage (OpenAI / Qwen-compat)
    meta = getattr(response, "response_metadata", {}) or {}
    usage = meta.get("token_usage") or meta.get("usage") or {}
    # 2) usage_metadata (newer LangChain convention)
    if not usage:
        usage_md = getattr(response, "usage_metadata", {}) or {}
        if usage_md:
            return {
                "prompt": int(usage_md.get("input_tokens", 0) or 0),
                "completion": int(usage_md.get("output_tokens", 0) or 0),
            }
    return {
        "prompt": int(usage.get("prompt_tokens", 0) or 0),
        "completion": int(usage.get("completion_tokens", 0) or 0),
    }


async def invoke_llm(
    user_prompt: str,
    *,
    system_prompt: str | None = None,
    temperature: float = 0.3,
    timeout: int = 90,
    max_prompt_chars: int = 8000,
    span_emit: Callable[[dict], Awaitable[None]] | None = None,
    task_id: str = "",
) -> dict[str, Any]:
    """Single LLM call with semaphore, truncation, and exception classification.

    Returns a dict with the following keys (always present):
        text: str           — generated text (empty on error)
        tokens: dict        — {"prompt": int, "completion": int}
        elapsed: float      — wall-clock seconds
        error_category: str | None  — ErrorCategory.value or None on success
        error: str | None   — str(exception) or None on success
        prompt_chars: int   — final prompt length after truncation
    """
    # Truncate eagerly to protect against oversized stats dicts
    truncated_user = truncate(user_prompt, max_prompt_chars)
    if system_prompt:
        truncated_system = truncate(system_prompt, max_prompt_chars // 4)
    else:
        truncated_system = None

    prompt_chars = len(truncated_user) + (len(truncated_system) if truncated_system else 0)
    start = time.monotonic()

    if span_emit:
        await span_emit(make_span("llm_call", task_id, status="start", input={
            "prompt_chars": prompt_chars,
            "temperature": temperature,
            "system_preview": (truncated_system or "")[:200],
            "user_preview": truncated_user[:400],
        }))

    try:
        import httpx
        from backend.config import get_settings
        from langchain_openai import ChatOpenAI

        settings = get_settings()
        # Bind a fresh httpx.AsyncClient to the *current* event loop. Without
        # this, langchain_openai/openai SDK caches a wrapper at module level
        # that stays bound to whichever event loop first used it; subsequent
        # pytest-asyncio tests (or any process that spins up a fresh loop)
        # then fail with "Invalid http_client argument: Expected instance of
        # httpx.AsyncClient" even though the wrapper IS a subclass — what's
        # actually wrong is that the underlying transport is closed.
        http_client = httpx.AsyncClient(timeout=timeout)
        llm = ChatOpenAI(
            base_url=settings.QWEN_API_BASE,
            api_key=settings.QWEN_API_KEY,
            model=settings.QWEN_MODEL,
            temperature=temperature,
            request_timeout=timeout,
            extra_body={"enable_thinking": False},
            http_async_client=http_client,
        )

        sem = _get_semaphore()
        async with sem:
            try:
                if truncated_system:
                    messages = [
                        {"role": "system", "content": truncated_system},
                        {"role": "user", "content": truncated_user},
                    ]
                    response = await llm.ainvoke(messages)
                else:
                    response = await llm.ainvoke(truncated_user)
            finally:
                await http_client.aclose()

        raw = response.content if hasattr(response, "content") else str(response)
        text = _strip_think_tags(raw)
        tokens = _extract_usage(response)
        elapsed = time.monotonic() - start
        if span_emit:
            await span_emit(make_span("llm_call", task_id, status="ok", output={
                "text_preview": text[:400],
                "tokens": tokens,
                "latency_ms": int(elapsed * 1000),
            }))
        return {
            "text": text,
            "tokens": tokens,
            "elapsed": elapsed,
            "error_category": None,
            "error": None,
            "prompt_chars": prompt_chars,
        }

    except Exception as e:
        category = classify_exception(e)
        elapsed = time.monotonic() - start
        logger.warning(
            "LLM invoke failed [%s] after %.2fs (prompt %d chars): %s",
            category.value, elapsed, prompt_chars, e,
        )
        if span_emit:
            await span_emit(make_span("llm_call", task_id, status="error", output={
                "error_category": category.value,
                "error": str(e)[:300],
                "latency_ms": int(elapsed * 1000),
            }))
        return {
            "text": "",
            "tokens": {},
            "elapsed": elapsed,
            "error_category": category.value,
            "error": str(e),
            "prompt_chars": prompt_chars,
        }


# ── Compact-JSON helper for stats-rich prompts ───────────────

def compact_stats_dict(stats: dict, max_cols: int = 5, max_groups: int = 8) -> dict:
    """Trim a summary_stats dict before serializing into a prompt.

    Heuristics:
    - Top-level dict with >max_groups keys → keep first ``max_groups`` and
      replace rest with a single ``{"__truncated__": "N more groups"}`` entry.
    - Each group-level dict with >max_cols columns → keep first ``max_cols``.
    - Numeric floats rounded to 2 decimals to cut prompt bloat.
    """
    if not isinstance(stats, dict):
        return stats

    def _round(v: Any) -> Any:
        if isinstance(v, float):
            return round(v, 2)
        if isinstance(v, dict):
            return {k: _round(x) for k, x in v.items()}
        return v

    def _trim_cols(d: dict) -> dict:
        keys = list(d.keys())
        if len(keys) <= max_cols:
            return {k: _round(d[k]) for k in keys}
        kept = {k: _round(d[k]) for k in keys[:max_cols]}
        kept["__truncated_cols__"] = f"另有 {len(keys) - max_cols} 列"
        return kept

    groups = list(stats.keys())
    if len(groups) > max_groups:
        out: dict[str, Any] = {}
        for k in groups[:max_groups]:
            v = stats[k]
            out[k] = _trim_cols(v) if isinstance(v, dict) else _round(v)
        out["__truncated_groups__"] = f"另有 {len(groups) - max_groups} 组"
        return out

    return {
        k: (_trim_cols(v) if isinstance(v, dict) else _round(v))
        for k, v in stats.items()
    }


# ── Domain inference (used by descriptive/summary/attribution) ──

_DOMAIN_KEYWORDS = {
    "throughput": ("throughput", "港", "吞吐"),
    "customer":   ("customer", "客户"),
    "asset":      ("asset", "equipment", "资产", "设备"),
}


def infer_domain(template_id: str | None, default: str = "generic") -> str:
    """Guess business domain from a template_id or task hint.

    Returns one of: "throughput" / "customer" / "asset" / "generic".
    """
    if not template_id:
        return default
    lower = template_id.lower()
    for domain, kws in _DOMAIN_KEYWORDS.items():
        if any(kw in lower for kw in kws):
            return domain
    return default

"""Record/replay LLM wrappers.

Two wrappers cover both LLM entry points used in the codebase:

  RecordedLangChainLLM
      Wraps a LangChain BaseChatModel (ChatOpenAI). Intercepts ainvoke().
      Used to patch backend.agent.graph.build_llm.

  RecordedInvokeLLM
      Drop-in replacement for backend.tools._llm.invoke_llm. Same async
      signature, returns the same dict shape.

Both share one pluggable cache directory and one operating mode.
"""
from __future__ import annotations

import re
import time
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable

from .llm_cache import (
    CacheMissError,
    cache_key,
    have_api_key,
    load,
    make_entry,
    store,
)


class RecordingMode(str, Enum):
    REPLAY = "replay"                  # only cache hits; miss → CacheMissError
    RECORD_MISSING = "record-missing"  # cache hits; misses → call real LLM + store
    RECORD_ALL = "record-all"          # always call real LLM + overwrite cache
    PASSTHROUGH = "passthrough"        # always call real LLM, never write cache


# ── shared helpers ──────────────────────────────────────────────


class _FakeAIMessage:
    """Minimal stub matching LangChain's AIMessage shape (.content)."""
    def __init__(self, content: str):
        self.content = content
        self.response_metadata: dict = {}
        self.usage_metadata: dict = {}


def _prompt_to_text(prompt: Any) -> str:
    """Normalise LangChain's ainvoke input variants into a single string."""
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, list):
        # list of dicts {role, content}
        parts: list[str] = []
        for m in prompt:
            if isinstance(m, dict):
                role = m.get("role", "user")
                content = m.get("content", "")
                parts.append(f"[{role}]\n{content}")
            else:
                parts.append(str(m))
        return "\n\n".join(parts)
    return str(prompt)


# ── RecordedLangChainLLM ───────────────────────────────────────


class RecordedLangChainLLM:
    """Wrap a LangChain BaseChatModel with cache-backed ainvoke()."""

    def __init__(
        self,
        real_llm: Any | None,
        *,
        cache_dir: Path,
        mode: RecordingMode,
        model: str = "",
        temperature: float = 0.1,
        normalize: list[tuple[re.Pattern, str]] | None = None,
        test_id: str = "",
    ):
        self._real = real_llm
        self._cache_dir = cache_dir
        self._mode = mode
        self._model = model or getattr(real_llm, "model_name", "") or getattr(real_llm, "model", "")
        self._temp = temperature
        self._normalize = normalize
        self._test_id = test_id
        self.calls: list[dict] = []  # for assertions in tests

    async def ainvoke(self, prompt: Any, **kw) -> _FakeAIMessage:
        text = _prompt_to_text(prompt)
        # Detect a leading [system] block so it can be cached separately
        system, user = None, text
        if text.startswith("[system]\n"):
            split = text.split("\n\n[user]\n", 1)
            if len(split) == 2:
                system = split[0][len("[system]\n"):]
                user = split[1]

        key, blob = cache_key(
            user_prompt=user, system_prompt=system,
            model=self._model, temperature=self._temp,
            extra_normalizers=self._normalize,
        )
        self.calls.append({"key": key, "user": user[:200]})

        if self._mode == RecordingMode.REPLAY:
            entry = load(self._cache_dir, key)
            if entry is None:
                raise CacheMissError(
                    f"No cached LLM response (langchain) for key {key[:8]}… "
                    f"in test {self._test_id}. Run with --llm-mode=record-missing."
                )
            return _FakeAIMessage(entry["response"]["text"])

        if self._mode == RecordingMode.RECORD_MISSING:
            entry = load(self._cache_dir, key)
            if entry is not None:
                return _FakeAIMessage(entry["response"]["text"])

        # RECORD_ALL / RECORD_MISSING (cache miss) / PASSTHROUGH
        if self._real is None or not have_api_key():
            raise RuntimeError(
                "LLM mode requires real LLM but no client configured / no API key. "
                "Set QWEN_API_KEY / OPENAI_API_KEY / DEEPSEEK_R1_API_KEY."
            )

        t0 = time.monotonic()
        real_resp = await self._real.ainvoke(prompt, **kw)
        dt_ms = int((time.monotonic() - t0) * 1000)
        text_out = real_resp.content if hasattr(real_resp, "content") else str(real_resp)

        if self._mode != RecordingMode.PASSTHROUGH:
            entry = make_entry(
                key=key, normalized_blob=blob,
                user_prompt=user, system_prompt=system,
                model=self._model, temperature=self._temp,
                response_text=text_out,
                latency_ms=dt_ms, test_id=self._test_id,
            )
            store(self._cache_dir, key, entry)
        return _FakeAIMessage(text_out)


# ── RecordedInvokeLLM ──────────────────────────────────────────


class RecordedInvokeLLM:
    """Cache-backed replacement for `backend.tools._llm.invoke_llm`.

    Matches the original signature and returns a dict with the same keys.
    """

    def __init__(
        self,
        real_invoke: Callable[..., Awaitable[dict]] | None,
        *,
        cache_dir: Path,
        mode: RecordingMode,
        model: str = "qwen-default",
        normalize: list[tuple[re.Pattern, str]] | None = None,
        test_id: str = "",
    ):
        self._real = real_invoke
        self._cache_dir = cache_dir
        self._mode = mode
        self._model = model
        self._normalize = normalize
        self._test_id = test_id
        self.calls: list[dict] = []

    async def __call__(self, *args, **kwargs) -> dict:
        return await self.ainvoke(*args, **kwargs)

    async def ainvoke(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.3,
        timeout: int = 90,
        max_prompt_chars: int = 8000,
        span_emit: Callable[[dict], Awaitable[None]] | None = None,
        task_id: str = "",
        _semaphore: Any = None,
    ) -> dict:
        key, blob = cache_key(
            user_prompt=user_prompt, system_prompt=system_prompt,
            model=self._model, temperature=temperature,
            extra_normalizers=self._normalize,
        )
        self.calls.append({"key": key, "task_id": task_id})

        if self._mode == RecordingMode.REPLAY:
            entry = load(self._cache_dir, key)
            if entry is None:
                raise CacheMissError(
                    f"No cached LLM response (invoke_llm) for key {key[:8]}… "
                    f"in test {self._test_id}. Run with --llm-mode=record-missing."
                )
            r = entry["response"]
            return {
                "text": r["text"],
                "tokens": r.get("usage", {}),
                "elapsed": r.get("latency_ms", 0) / 1000.0,
                "error_category": None,
                "error": None,
                "prompt_chars": len(user_prompt) + len(system_prompt or ""),
            }

        if self._mode == RecordingMode.RECORD_MISSING:
            entry = load(self._cache_dir, key)
            if entry is not None:
                r = entry["response"]
                return {
                    "text": r["text"],
                    "tokens": r.get("usage", {}),
                    "elapsed": r.get("latency_ms", 0) / 1000.0,
                    "error_category": None,
                    "error": None,
                    "prompt_chars": len(user_prompt) + len(system_prompt or ""),
                }

        if self._real is None or not have_api_key():
            raise RuntimeError(
                "LLM mode requires real LLM but no client / API key configured."
            )

        result = await self._real(
            user_prompt,
            system_prompt=system_prompt, temperature=temperature,
            timeout=timeout, max_prompt_chars=max_prompt_chars,
            span_emit=span_emit, task_id=task_id, _semaphore=_semaphore,
        )

        if self._mode != RecordingMode.PASSTHROUGH and not result.get("error"):
            entry = make_entry(
                key=key, normalized_blob=blob,
                user_prompt=user_prompt, system_prompt=system_prompt,
                model=self._model, temperature=temperature,
                response_text=result.get("text", ""),
                tokens=result.get("tokens", {}),
                latency_ms=int(result.get("elapsed", 0) * 1000),
                test_id=self._test_id,
            )
            store(self._cache_dir, key, entry)
        return result

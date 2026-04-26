"""File-based LLM response cache.

Cache layout:
    {cache_dir}/{shard}/{key}.json
where shard = first 2 chars of sha256(key) → keeps any single dir < 256 entries.

Each file is a self-describing record (see `make_entry`).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .normalize import apply_normalizers


def cache_key(
    *,
    user_prompt: str,
    system_prompt: str | None = None,
    model: str = "",
    temperature: float = 0.0,
    extra_normalizers: list[tuple[re.Pattern, str]] | None = None,
) -> tuple[str, str]:
    """Return ``(key, normalized_blob)``.

    `key` is sha256 hash; `normalized_blob` is what was hashed (kept for
    debugging — written into the cache entry so we can diff prompt drift).
    """
    norm_user = apply_normalizers(user_prompt, extra_normalizers)
    norm_system = apply_normalizers(system_prompt or "", extra_normalizers)
    blob = (
        f"MODEL={model}\n"
        f"TEMP={round(temperature, 3)}\n"
        f"SYSTEM:\n{norm_system}\n"
        f"USER:\n{norm_user}\n"
    )
    h = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return h, blob


def cache_path(cache_dir: Path, key: str) -> Path:
    shard = key[:2]
    return cache_dir / shard / f"{key}.json"


def load(cache_dir: Path, key: str) -> dict | None:
    p = cache_path(cache_dir, key)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def store(cache_dir: Path, key: str, entry: dict) -> Path:
    p = cache_path(cache_dir, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def make_entry(
    *,
    key: str,
    normalized_blob: str,
    user_prompt: str,
    system_prompt: str | None,
    model: str,
    temperature: float,
    response_text: str,
    tokens: dict[str, int] | None = None,
    latency_ms: int = 0,
    test_id: str = "",
    extra: dict[str, Any] | None = None,
) -> dict:
    return {
        "key": key,
        "request": {
            "model": model,
            "temperature": temperature,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "normalized_for_key": normalized_blob,
        },
        "response": {
            "text": response_text,
            "usage": tokens or {},
            "latency_ms": latency_ms,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "recorded_by": test_id,
        },
        **(extra or {}),
    }


class CacheMissError(KeyError):
    """Raised in REPLAY mode when no cached entry exists for the prompt."""


def have_api_key() -> bool:
    """Heuristic: a recordable LLM key is configured in env."""
    return bool(
        os.getenv("QWEN_API_KEY") or os.getenv("OPENAI_API_KEY")
        or os.getenv("DEEPSEEK_R1_API_KEY")
    )

"""In-memory LRU cache for search results.

Cache key: hash(query, provider, lang)
TTL: 1 hour (3600 seconds)
Max entries: 128
"""
from __future__ import annotations

import hashlib
import logging
import time as _time
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger("analytica.tools.search_cache")

_MAX_ENTRIES = 128
_TTL_SECONDS = 3600  # 1 hour

_cache: OrderedDict[str, tuple[list[dict[str, Any]], float]] = OrderedDict()


def _make_key(query: str, provider: str, lang: str) -> str:
    """Produce a stable cache key."""
    raw = f"{query}|{provider}|{lang}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached(
    query: str, *, provider: str = "mcp", lang: str = "zh-CN"
) -> Optional[list[dict[str, Any]]]:
    """Return cached hits if present and not expired, otherwise None."""
    key = _make_key(query, provider, lang)
    entry = _cache.get(key)
    if entry is None:
        return None
    hits, ts = entry
    if _time.monotonic() - ts > _TTL_SECONDS:
        del _cache[key]
        return None
    # Move to end (LRU: most recently used)
    _cache.move_to_end(key)
    logger.debug("Cache hit for query=%r", query[:60])
    return hits


def set_cached(
    query: str,
    hits: list[dict[str, Any]],
    *,
    provider: str = "mcp",
    lang: str = "zh-CN",
) -> None:
    """Store search results in cache. Evicts oldest entry if at capacity."""
    key = _make_key(query, provider, lang)
    _cache[key] = (hits, _time.monotonic())
    _cache.move_to_end(key)
    if len(_cache) > _MAX_ENTRIES:
        evicted = _cache.popitem(last=False)
        logger.debug("Cache evicted key=%s", evicted[0][:16])
    logger.debug("Cache stored for query=%r (%d hits)", query[:60], len(hits))


def clear_cache() -> None:
    """Clear all cached entries (useful for tests)."""
    _cache.clear()


def cache_stats() -> dict[str, Any]:
    """Return cache statistics for observability."""
    now = _time.monotonic()
    total = len(_cache)
    expired = sum(
        1 for _, (_, ts) in _cache.items() if now - ts > _TTL_SECONDS
    )
    return {
        "total": total,
        "expired": expired,
        "max_entries": _MAX_ENTRIES,
        "ttl_seconds": _TTL_SECONDS,
    }

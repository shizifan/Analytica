"""Tests for search result cache."""
from __future__ import annotations

import time as _time
from unittest.mock import patch

import pytest

from backend.tools.data._search_cache import (
    cache_stats,
    clear_cache,
    get_cached,
    set_cached,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    """Ensure a clean cache before and after each test."""
    clear_cache()
    yield
    clear_cache()


class TestSearchCache:
    """Verify in-memory LRU cache behaviour."""

    def test_cache_miss_returns_none(self):
        assert get_cached("nonexistent query") is None

    def test_cache_hit_returns_hits(self):
        hits = [{"title": "test", "url": "https://example.com"}]
        set_cached("辽港集团 吞吐量", hits)
        result = get_cached("辽港集团 吞吐量")
        assert result == hits

    def test_cache_key_uniqueness(self):
        hits_a = [{"title": "A"}]
        hits_b = [{"title": "B"}]
        set_cached("query a", hits_a)
        set_cached("query b", hits_b)
        assert get_cached("query a") == hits_a
        assert get_cached("query b") == hits_b

    def test_cache_different_provider_different_key(self):
        hits_mcp = [{"title": "mcp_result"}]
        hits_tavily = [{"title": "tavily_result"}]
        set_cached("辽港", hits_mcp, provider="mcp")
        set_cached("辽港", hits_tavily, provider="tavily")
        assert get_cached("辽港", provider="mcp") == hits_mcp
        assert get_cached("辽港", provider="tavily") == hits_tavily

    def test_cache_expiry(self):
        hits = [{"title": "expired"}]
        with patch("backend.tools.data._search_cache._time.monotonic") as mock_time:
            mock_time.return_value = 1000.0
            set_cached("辽港", hits)
            # Advance past TTL (3600s)
            mock_time.return_value = 1000.0 + 3601.0
            assert get_cached("辽港") is None

    def test_cache_lru_eviction(self):
        """Insert 129 entries, verify only 128 remain (oldest evicted)."""
        for i in range(129):
            set_cached(f"query_{i}", [{"id": i}])
        assert get_cached("query_0") is None  # oldest evicted
        assert get_cached("query_1") is not None  # still there
        assert get_cached("query_128") is not None  # most recent
        assert cache_stats()["total"] == 128

    def test_clear_cache(self):
        set_cached("辽港", [{"title": "test"}])
        assert get_cached("辽港") is not None
        clear_cache()
        assert get_cached("辽港") is None
        assert cache_stats()["total"] == 0

    def test_cache_stats(self):
        set_cached("辽港", [{"title": "test"}])
        stats = cache_stats()
        assert stats["total"] == 1
        assert stats["max_entries"] == 128
        assert stats["ttl_seconds"] == 3600

"""Timeout / concurrency / retry — centralized configuration.

Single source of truth for execution.py and _llm.py.  All values are
read from ``Settings`` (pydantic-settings, backed by .env) and can be
overridden per-environment without touching code.

Import pattern:
    from backend.timeout_config import (
        get_concurrency_limits,
        get_timeout_profiles,
        get_retry_policies,
        get_global_llm_limit,
    )
"""

from backend.config import get_settings


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _parse_timeout(value: str) -> tuple[int, int, float]:
    """Parse "lower,upper,multiplier" → (lo, hi, mult)."""
    parts = value.strip().split(",")
    if len(parts) != 3:
        raise ValueError(f"Invalid timeout profile: {value!r}")
    return int(parts[0]), int(parts[1]), float(parts[2])


# ---------------------------------------------------------------------------
# public API — mirrors execution.py's _CONCURRENCY_LIMITS / _TIMEOUT_PROFILE
# ---------------------------------------------------------------------------

def get_concurrency_limits() -> dict[str, int]:
    s = get_settings()
    return {
        "data_fetch":    s.ANALYTICA_CONCURRENCY_DATA_FETCH,
        "analysis":      s.ANALYTICA_CONCURRENCY_ANALYSIS,
        "visualization": s.ANALYTICA_CONCURRENCY_VISUALIZATION,
        "report_gen":    s.ANALYTICA_CONCURRENCY_REPORT_GEN,
        "search":        s.ANALYTICA_CONCURRENCY_SEARCH,
        "_default":      3,
    }


def get_timeout_profiles() -> dict[str, tuple[int, int, float]]:
    s = get_settings()
    return {
        "data_fetch":    _parse_timeout(s.ANALYTICA_TIMEOUT_DATA_FETCH),
        "analysis":      _parse_timeout(s.ANALYTICA_TIMEOUT_ANALYSIS),
        "visualization": _parse_timeout(s.ANALYTICA_TIMEOUT_VISUALIZATION),
        "report_gen":    _parse_timeout(s.ANALYTICA_TIMEOUT_REPORT_GEN),
        "search":        _parse_timeout(s.ANALYTICA_TIMEOUT_SEARCH),
        "_default":      (15, 90, 3.0),
    }


def get_retry_policies() -> dict[str, tuple[int, frozenset[str]]]:
    s = get_settings()
    return {
        "data_fetch":    (3, frozenset({"TIMEOUT", "SERVER_ERROR", "RATE_LIMIT"})),
        "analysis":      (
            2,
            frozenset({"RATE_LIMIT"} | ({"TIMEOUT"} if s.ANALYTICA_RETRY_ANALYSIS_RETRY_TIMEOUT else set())),
        ),
        "visualization": (1, frozenset()),
        "report_gen":    (
            (2 if s.ANALYTICA_RETRY_REPORT_GEN_ENABLED else 1),
            frozenset({"TIMEOUT", "RATE_LIMIT"}) if s.ANALYTICA_RETRY_REPORT_GEN_ENABLED else frozenset(),
        ),
        "search":        (2, frozenset({"TIMEOUT", "SERVER_ERROR", "RATE_LIMIT"})),
        "_default":      (1, frozenset()),
    }


def get_global_llm_limit() -> int:
    return get_settings().ANALYTICA_LLM_CONCURRENCY

"""Query sanitizer — rules-based rewriting before search provider calls.

Removes internal naming patterns, login/employee_id patterns, and
internal terminology from search queries. Always rewrites, never rejects.
"""
from __future__ import annotations

import logging
import re as _re
from typing import Sequence, Tuple

logger = logging.getLogger("analytica.tools.search_sanitizer")

# Each rule: (compiled_regex, replacement_string, description)
_RULES: Sequence[Tuple[_re.Pattern, str, str]] = [
    # 1. Internal employee IDs / session-like tokens
    (_re.compile(r'\b[eE][mM][pP]_?\d{4,}\b'), '[内部ID已移除]',
     'employee_id_pattern'),
    # 2. Long hex/internal codes (API response field names, UUID residuals)
    (_re.compile(r'\b[a-fA-F0-9]{16,}\b'), '',
     'long_hex_code'),
    # 3. Login / auth token residuals
    (_re.compile(r'\b(token|auth|session|credential)s?[=:]\S+', _re.IGNORECASE), '',
     'auth_token'),
    # 4. Internal API endpoint name patterns (camelCase with obvious internal prefixes)
    (_re.compile(r'\b(get|post|put|delete)[A-Z][a-zA-Z]{10,}\b'), '',
     'api_method_name'),
    # 5. Internal pipeline/table references (e.g. "dwd_xxx_xxx", "ods_xxx")
    (_re.compile(r'\b(dwd|ods|dim|ads|tmp)_[a-z_]{5,}\b'), '',
     'internal_table_ref'),
]


def sanitize_query(q: str) -> str:
    """Apply all sanitisation rules to a query string.

    Each matching pattern is replaced with its replacement string.
    Rules never reject — they always produce a (possibly modified) output.
    The original intent is preserved by removing only the offending fragments.

    Args:
        q: Raw query string from LLM planner or user input.

    Returns:
        Sanitised query string. Identical to input if no rules matched.
    """
    original = q
    for pattern, replacement, rule_name in _RULES:
        q = pattern.sub(replacement, q)
    if q != original:
        logger.info("Sanitized query: %r → %r", original[:120], q[:120])
    # Remove double spaces / trailing whitespace that may result from removals
    return _re.sub(r' +', ' ', q).strip()

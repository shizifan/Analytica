"""Prompt content normalisation before hashing.

The same logical prompt may carry non-deterministic content (today's date,
session UUIDs, task IDs, ISO timestamps). Normalising these before hashing
keeps cache keys stable across days / runs.

Tests can extend with their own normalizers via `RecordedLLM(normalize=[...])`.
"""
from __future__ import annotations

import re

# (pattern, replacement) — applied in order.
DEFAULT_NORMALIZERS: list[tuple[re.Pattern, str]] = [
    # Today's date references in prompt body
    (re.compile(r"今天是\s*\d{4}-\d{2}-\d{2}"),                "今天是<DATE>"),
    (re.compile(r"Today is\s*\d{4}-\d{2}-\d{2}"),              "Today is <DATE>"),
    (re.compile(r"当前日期[:：]\s*\d{4}-\d{2}-\d{2}"),         "当前日期: <DATE>"),
    # Generic ISO timestamps
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?"),  "<TIMESTAMP>"),
    # UUIDs (session_id, plan_id, etc.)
    (re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"), "<UUID>"),
    # session_id / plan_id key=value forms
    (re.compile(r"session_id[:\s=\"']+[\w-]+"),                "session_id=<UUID>"),
    (re.compile(r"plan_id[:\s=\"']+[\w-]+"),                   "plan_id=<UUID>"),
    # Trailing whitespace
    (re.compile(r"[ \t]+\n"),                                  "\n"),
]


def apply_normalizers(text: str, extra: list[tuple[re.Pattern, str]] | None = None) -> str:
    """Apply default + extra normalisers to a prompt before hashing."""
    out = text
    for pat, repl in DEFAULT_NORMALIZERS:
        out = pat.sub(repl, out)
    if extra:
        for pat, repl in extra:
            out = pat.sub(repl, out)
    return out

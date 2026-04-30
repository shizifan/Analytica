"""Table highlight rule resolver — Phase 4.2.

``TableBlock.highlight_rules`` is a list of per-cell visual emphasis
rules. Each rule shape (LLM-friendly):

  {"col": "<header name>", "color": "<semantic>"}
      → paint the entire data column

  {"row": <0-based body row idx>, "color": "<semantic>"}
      → paint the entire row (body only; header never gets coloured)

  {"col": "<header>", "row": <idx>, "color": "<semantic>"}
      → paint a specific cell (intersection)

``color`` is one of the semantic tokens below; the renderer maps to the
active theme's RGB tuple. Centralising the mapping keeps "negative" red
consistent across DOCX / PPT / HTML.

This Phase 4.2 helper intentionally stays simple — predicate-based
rules ("max", "min", "rank<=3", "> 0") are out of scope until a
follow-up phase observes the LLM planner actually wants them. Doing
half a predicate language now would invite scope creep.
"""
from __future__ import annotations

from typing import Any, Iterable


_SEMANTIC_TOKENS = {
    "positive", "negative", "neutral", "accent",
    "gold", "silver", "bronze",
    "primary", "secondary",
}


def resolve_color(token: str | None, theme) -> tuple[int, int, int] | None:
    """Map a semantic colour token to the active theme's RGB tuple.

    Unknown tokens return ``None`` so the caller can skip the rule
    rather than colouring incorrectly. Special non-theme tokens
    (gold/silver/bronze) use fixed metallics — they're not in the
    theme yet because rank highlighting is only one of several
    optional flourishes.
    """
    if not token:
        return None
    token = token.lower().strip()
    if token == "positive":
        return theme.positive
    if token == "negative":
        return theme.negative
    if token == "neutral":
        return theme.neutral
    if token == "accent":
        return theme.accent
    if token == "primary":
        return theme.primary
    if token == "secondary":
        return theme.secondary
    if token == "gold":
        return (0xFF, 0xD7, 0x00)
    if token == "silver":
        return (0xC0, 0xC0, 0xC0)
    if token == "bronze":
        return (0xCD, 0x7F, 0x32)
    return None


def resolve_cell_highlights(
    headers: Iterable[str],
    n_rows: int,
    rules: list[dict[str, Any]],
    theme,
) -> dict[tuple[int, int], tuple[int, int, int]]:
    """Resolve highlight rules into a per-cell colour map.

    Returns ``{(row_idx, col_idx): rgb_tuple}`` for every body cell that
    should be coloured. ``row_idx`` is 0-based **after** the header row;
    callers add their own offset when writing OOXML / HTML rows.

    Unknown / partial / out-of-range rules are silently dropped — the
    spec calls for "never break rendering" semantics so misconfigured
    LLM output degrades to the un-highlighted table.
    """
    headers_list = list(headers)
    out: dict[tuple[int, int], tuple[int, int, int]] = {}
    if not rules:
        return out

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rgb = resolve_color(rule.get("color"), theme)
        if rgb is None:
            continue

        col_name = rule.get("col")
        row_idx = rule.get("row")
        col_idx = (
            headers_list.index(col_name)
            if isinstance(col_name, str) and col_name in headers_list
            else None
        )

        if row_idx is None and col_idx is not None:
            # Whole-column rule — paint every body cell in that column
            for r in range(n_rows):
                out[(r, col_idx)] = rgb
        elif col_idx is None and isinstance(row_idx, int):
            # Whole-row rule — paint every column in that row
            if 0 <= row_idx < n_rows:
                for c in range(len(headers_list)):
                    out[(row_idx, c)] = rgb
        elif col_idx is not None and isinstance(row_idx, int):
            # Single-cell rule
            if 0 <= row_idx < n_rows:
                out[(row_idx, col_idx)] = rgb
        # else: rule has neither valid col nor row — skip

    return out


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    """6-digit hex string without leading '#' (matches SlideCommand /
    pptxgenjs convention)."""
    return f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"

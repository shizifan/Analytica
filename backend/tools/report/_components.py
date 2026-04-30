"""Cross-backend visual component contracts — Phase 5.1.

Each ``*Spec`` dataclass declares the **proportional** visual contract
for a recurring component (KPI card / callout / section cover / grid
column). The four renderers reference these specs to keep visuals
coherent across DOCX / PPT / HTML / Markdown.

Why dataclasses (not just constants):
- Future presets (e.g. compact / wide layouts) plug in by subclassing
  or overriding via ``replace()`` — easier than scattering magic
  numbers across 4 renderers.
- ``Theme`` carries colours / fonts / radii / shadows; component specs
  carry **structure** (relative widths, height ratios, positions).
  Combined they fully specify a visual block.

Phase 5.1 ships the contracts + a couple of backend-agnostic helpers
(``derive_kpi_card_dimensions``). Renderers continue to embed their
own absolute coordinate maths; the specs serve as the *single source
of truth* the renderers should consult when those numbers need to
change.

Cross-backend test ``test_component_contracts.py`` will assert each
renderer's output respects the spec — currently the visual params live
inline in ``_renderers/*.py``. Phase 5+ refactors will gradually
replace those inline numbers with reads from these specs.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


# ---------------------------------------------------------------------------
# KPI card (used by Phase 3.5 KPI overview slide + Phase 4.3 trend KPI rows)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KpiCardSpec:
    """KPI 卡视觉契约（4 端 emit_kpi_row + KPI overview slide 共用）.

    All sizes are *proportional* — the active backend converts them
    to its own unit (DOCX cells, PPT inches, HTML rem/px).
    """
    # Relative position of the value text within the card height (0-1)
    value_y_ratio: float = 0.45
    # Ratio of label font size to value font size (typography hierarchy)
    label_size_ratio: float = 0.31  # 11pt vs 36pt = 0.30 ≈ 0.31
    # Where the trend accent stripe sits: top / left / bottom / none
    accent_position: Literal["top", "left", "bottom", "none"] = "bottom"
    # Whether to shadow-elevate the card off the slide background
    has_shadow: bool = True
    # Whether the card has rounded corners (DOCX may ignore)
    rounded: bool = True


# ---------------------------------------------------------------------------
# Callout block (Phase 4.1 risk / info messages)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CalloutSpec:
    """Callout 强调框视觉契约（warn / info）.

    Renderers map ``side`` to:
    - HTML: ``border-left`` style
    - DOCX: ``w:pBdr/w:left`` element
    - PPT (PptxGenJS): rounded shape with the same colour as fill border
    - Markdown: blockquote prefix (no border concept)
    """
    side: Literal["left", "top", "all"] = "left"
    # Whether to prefix the text with an emoji marker (⚠ / 💡)
    show_emoji: bool = True
    # Whether the title label is bold ("注意" / "提示")
    bold_title: bool = True
    # Apply tinted background fill (vs only the side accent)
    has_background: bool = True


# ---------------------------------------------------------------------------
# Section cover (Phase 3.1 chapter divider)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SectionCoverSpec:
    """章节分节封面视觉契约.

    Drives ``emit_section_cover`` across 4 backends. PPT uses these
    proportions to lay out the dark divider slide; DOCX uses just the
    ``show_index`` flag to decide whether to prepend the section
    number to the H1 heading.
    """
    # Whether to print the section index number (e.g. "01") prominently
    show_index: bool = True
    # Position of the index number relative to the title:
    #   "above" — number above title
    #   "left"  — number left of title (wide-screen layouts)
    #   "inline" — same line as title prefix
    index_position: Literal["above", "left", "inline"] = "above"
    # Background uses theme.cover_bg (None ⇒ primary). When True the
    # text colour switches to theme.cover_text (None ⇒ white).
    dark_background: bool = True
    # Optional accent stripe under the title (Phase 3.1 keeps it on)
    has_accent_stripe: bool = True


# ---------------------------------------------------------------------------
# Comparison grid column (Phase 3.2 三栏建议)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GridColumnSpec:
    """ComparisonGrid 单列视觉契约.

    Renderers respect ``title_bar_position`` when laying out the
    column card. A ``"top"`` bar matches the SOP-aligned recommendation
    grid (Sprint 3 style); ``"left"`` is reserved for future variants.
    """
    title_bar_position: Literal["top", "left"] = "top"
    # Title bar height as a ratio of the column card height (0.1–0.3
    # works visually; 0.13 keeps the bar slim against the bullet body).
    title_bar_height_ratio: float = 0.13
    # Bullet style: "•" is the default;
    bullet_glyph: str = "•"
    # Maximum bullet items rendered per column before truncation
    max_items: int = 6


# ---------------------------------------------------------------------------
# Default specs (corporate-blue uses these directly)
# ---------------------------------------------------------------------------

DEFAULT_KPI_CARD = KpiCardSpec()
DEFAULT_CALLOUT = CalloutSpec()
DEFAULT_SECTION_COVER = SectionCoverSpec()
DEFAULT_GRID_COLUMN = GridColumnSpec()


# ---------------------------------------------------------------------------
# Layout helpers used across multiple renderers
# ---------------------------------------------------------------------------

def derive_kpi_card_dimensions(
    n_cards: int,
    canvas_width_inch: float = 8.0,
    canvas_y_inch: float = 1.3,
    canvas_height_inch: float = 4.5,
    canvas_x_offset_inch: float = 1.0,
    gap_inch: float = 0.2,
) -> list[tuple[float, float, float, float]]:
    """Return ``[(x, y, w, h), ...]`` for ``n_cards`` evenly distributed
    KPI cards. Used by the PPT KPI overview slide so 1, 2, 3, 4-card
    layouts share the same spacing logic.

    Caps at 4 cards (Phase 3.5 keeps overview compact).
    """
    n = max(1, min(int(n_cards), 4))
    card_w = canvas_width_inch / n - gap_inch * (n - 1) / n
    return [
        (
            canvas_x_offset_inch + i * (card_w + gap_inch),
            canvas_y_inch,
            card_w,
            canvas_height_inch,
        )
        for i in range(n)
    ]


def grid_column_layout(
    n_cols: int,
    canvas_width_inch: float = 8.8,
    margin_inch: float = 0.6,
    gap_inch: float = 0.2,
) -> list[tuple[float, float]]:
    """Return ``[(x, w), ...]`` for ``n_cols`` equal-width comparison
    grid columns. Used by ``emit_comparison_grid`` PPT renderers.
    """
    n = max(1, min(int(n_cols), 4))
    usable = canvas_width_inch - 2 * margin_inch - gap_inch * (n - 1)
    col_w = max(usable / n, 1.5)
    return [
        (margin_inch + i * (col_w + gap_inch), col_w)
        for i in range(n)
    ]


__all__ = [
    "KpiCardSpec",
    "CalloutSpec",
    "SectionCoverSpec",
    "GridColumnSpec",
    "DEFAULT_KPI_CARD",
    "DEFAULT_CALLOUT",
    "DEFAULT_SECTION_COVER",
    "DEFAULT_GRID_COLUMN",
    "derive_kpi_card_dimensions",
    "grid_column_layout",
    "replace",  # re-export so callers can `replace(spec, has_shadow=False)`
]

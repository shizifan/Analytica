"""Theme system for report generation — Phase 1 of Sprint 3 visual polish.

Phase 1 introduces the ``Theme`` dataclass abstraction. All visual
properties (colors, fonts, sizes, future: radii / shadows) live on a
single immutable object that renderers read from. The pre-Sprint-3
module-level constants (``PRIMARY``, ``RGB_PRIMARY``, ``FONT_CN``, …)
are still exported for backward compatibility — they are now derived
from the default ``corporate-blue`` preset.

Why a dataclass and not a TypedDict / dict:
- ``frozen=True`` catches accidental mutation in renderers.
- IDE / type-checker can verify field access.
- Future presets become a ``THEMES`` dict entry, not a parallel module.

Phase 4-5 visual-polish work extends the dataclass with
``chart_colors``, ``callout_*``, ``cover_*``, ``radius_*``,
``shadow_strength`` etc. Adding a field is forward-compatible: existing
preset(s) get a default, new presets must opt-in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ThemeName = Literal["corporate-blue"]


# ---------------------------------------------------------------------------
# Color helper — keep in sync with _pptxgen_commands.is_valid_hex6
# ---------------------------------------------------------------------------

def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    """RGB tuple → 6-digit hex without leading '#'."""
    return f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """6-digit hex (with or without '#') → RGB tuple."""
    s = hex_str.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


# ---------------------------------------------------------------------------
# Trend tokens — Phase 4.3
# ---------------------------------------------------------------------------

# Single source of truth for trend visuals across the four backends.
# - ``arrow``: glyph drawn next to a number / KPI value
# - ``color_attr``: name of the Theme field whose RGB tuple to use
# - ``css_attr``: corresponding ``css_<name>`` attribute (already
#   present on Theme as ``css_*`` properties)
TREND_TOKENS: dict[str, dict[str, str]] = {
    "positive": {
        "arrow": "↑", "color_attr": "positive", "css_attr": "css_positive",
    },
    "negative": {
        "arrow": "↓", "color_attr": "negative", "css_attr": "css_negative",
    },
    "flat": {
        "arrow": "→", "color_attr": "neutral", "css_attr": "css_neutral",
    },
}


def trend_arrow(token: str | None) -> str:
    """Return the arrow glyph for a trend token, or empty string."""
    if not token:
        return ""
    spec = TREND_TOKENS.get(token.lower())
    return spec["arrow"] if spec else ""


def trend_rgb(token: str | None, theme=None) -> tuple[int, int, int]:
    """Resolve a trend token to the active theme's RGB tuple.

    Unknown tokens fall back to ``neutral``. Pass ``theme=None`` to use
    the default ``corporate-blue`` preset.
    """
    th = theme or get_theme()
    if not token:
        return th.neutral
    spec = TREND_TOKENS.get(token.lower())
    if spec is None:
        return th.neutral
    return getattr(th, spec["color_attr"])


def trend_for_value(value: float | None) -> str:
    """Auto-classify a numeric delta into a trend token.

    Convenience for renderers that have raw growth rates instead of an
    LLM-supplied trend label. Zero ⇒ ``"flat"``; positive ⇒
    ``"positive"``; negative ⇒ ``"negative"``; ``None`` ⇒ ``"flat"``.
    """
    if value is None:
        return "flat"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "flat"


# ---------------------------------------------------------------------------
# Theme dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Theme:
    """Visual configuration consumed by all four BlockRenderer backends.

    Colors are stored as RGB tuples (Python representation) — derive
    hex strings via ``hex_*`` properties when emitting CSS / pptxgenjs
    payloads, or pass tuples directly to python-docx / python-pptx
    ``RGBColor`` constructors.

    Slide dimensions are in inches (matches pptxgenjs LAYOUT default).
    Font sizes are in points (callers wrap with ``Pt()`` as needed).
    """

    name: str

    # ── Colors (RGB tuple form — easiest for python-docx / python-pptx) ──
    primary: tuple[int, int, int]
    secondary: tuple[int, int, int]
    accent: tuple[int, int, int]
    positive: tuple[int, int, int]
    negative: tuple[int, int, int]
    neutral: tuple[int, int, int]
    bg_light: tuple[int, int, int]
    white: tuple[int, int, int]
    text_dark: tuple[int, int, int]

    # ── Fonts ─────────────────────────────────────────────────────────────
    font_cn: str
    font_num: str

    # ── Font sizes (points) ───────────────────────────────────────────────
    size_title: int
    size_h1: int
    size_h2: int
    size_h3: int
    size_body: int
    size_small: int
    size_kpi_large: int
    size_kpi_label: int
    size_table_header: int
    size_table_body: int

    # ── Slide dimensions (inches) ─────────────────────────────────────────
    slide_width: float
    slide_height: float

    # ── Phase 4-5 fields (defaulted so old presets/tests stay valid) ──────
    # 6-digit hex strings for chart series colors (no leading '#')
    chart_colors: tuple[str, ...] = (
        "1E3A5F", "F0A500", "E85454", "4CAF50", "9C27B0", "FF5722",
    )
    callout_warn_bg: tuple[int, int, int] = (0xFE, 0xF1, 0xF1)
    callout_warn_border: tuple[int, int, int] = (0xC6, 0x28, 0x28)
    callout_info_bg: tuple[int, int, int] = (0xE3, 0xF2, 0xFD)
    callout_info_border: tuple[int, int, int] = (0x19, 0x76, 0xD2)
    cover_bg: tuple[int, int, int] | None = None  # None → use primary
    cover_text: tuple[int, int, int] | None = None  # None → use white
    # Phase 3.5 + 5.3 — visual rhythm tokens (units depend on backend:
    # HTML uses pixels, DOCX/PPT compute their own conversion).
    radius_card: int = 8
    radius_callout: int = 4
    radius_button: int = 4
    shadow_strength: float = 0.3
    border_weight_table: int = 1   # px / OOXML border size
    border_weight_callout: int = 4
    padding_card: int = 16          # px equivalent
    padding_callout: int = 12
    spacing_section: int = 32       # vertical gap between sections (px)
    # Phase 5.4 — dark-mode opt-in flag for HTML; other backends ignore.
    dark_mode: bool = False

    # ── Hex string accessors (HTML/CSS, pptxgenjs) ────────────────────────

    @property
    def hex_primary(self) -> str:
        return _rgb_to_hex(self.primary)

    @property
    def hex_secondary(self) -> str:
        return _rgb_to_hex(self.secondary)

    @property
    def hex_accent(self) -> str:
        return _rgb_to_hex(self.accent)

    @property
    def hex_positive(self) -> str:
        return _rgb_to_hex(self.positive)

    @property
    def hex_negative(self) -> str:
        return _rgb_to_hex(self.negative)

    @property
    def hex_neutral(self) -> str:
        return _rgb_to_hex(self.neutral)

    @property
    def hex_bg_light(self) -> str:
        return _rgb_to_hex(self.bg_light)

    @property
    def hex_white(self) -> str:
        return _rgb_to_hex(self.white)

    @property
    def hex_text_dark(self) -> str:
        return _rgb_to_hex(self.text_dark)

    @property
    def hex_cover_bg(self) -> str:
        return _rgb_to_hex(self.cover_bg if self.cover_bg else self.primary)

    @property
    def hex_cover_text(self) -> str:
        return _rgb_to_hex(self.cover_text if self.cover_text else self.white)

    # ── CSS-style accessors (legacy `_theme.PRIMARY` returned `#1E3A5F`) ──

    @property
    def css_primary(self) -> str:
        return f"#{self.hex_primary}"

    @property
    def css_secondary(self) -> str:
        return f"#{self.hex_secondary}"

    @property
    def css_accent(self) -> str:
        return f"#{self.hex_accent}"

    @property
    def css_positive(self) -> str:
        return f"#{self.hex_positive}"

    @property
    def css_negative(self) -> str:
        return f"#{self.hex_negative}"

    @property
    def css_neutral(self) -> str:
        return f"#{self.hex_neutral}"

    @property
    def css_bg_light(self) -> str:
        return f"#{self.hex_bg_light}"

    @property
    def css_white(self) -> str:
        return f"#{self.hex_white}"

    @property
    def css_text_dark(self) -> str:
        return f"#{self.hex_text_dark}"


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

CORPORATE_BLUE = Theme(
    name="corporate-blue",
    primary=(0x1E, 0x3A, 0x5F),
    secondary=(0x2D, 0x5F, 0x8A),
    accent=(0xF0, 0xA5, 0x00),
    positive=(0x2E, 0x7D, 0x32),
    negative=(0xC6, 0x28, 0x28),
    neutral=(0x54, 0x6E, 0x7A),
    bg_light=(0xF5, 0xF7, 0xFA),
    white=(0xFF, 0xFF, 0xFF),
    text_dark=(0x33, 0x33, 0x33),
    font_cn="Microsoft YaHei",
    font_num="Calibri",
    size_title=28,
    size_h1=22,
    size_h2=18,
    size_h3=16,
    size_body=12,
    size_small=10,
    size_kpi_large=36,
    size_kpi_label=11,
    size_table_header=11,
    size_table_body=10,
    slide_width=10,
    slide_height=7.5,
)


THEMES: dict[str, Theme] = {
    "corporate-blue": CORPORATE_BLUE,
}


def get_theme(name: str | None = None) -> Theme:
    """Return a Theme by name, defaulting to ``corporate-blue``.

    Unknown names degrade silently to the default — matches the
    LLM-failure-fallback ethos in ``_outline_planner``: never break
    rendering for a misconfigured theme.
    """
    if name is None:
        return CORPORATE_BLUE
    return THEMES.get(name, CORPORATE_BLUE)


# ---------------------------------------------------------------------------
# Module-level constants — backward compatibility shim
# ---------------------------------------------------------------------------
# Existing renderer code uses ``from backend.tools.report import _theme as T``
# and reads ``T.PRIMARY`` (CSS hex string with #), ``T.RGB_PRIMARY`` (tuple),
# ``T.FONT_CN`` (string), ``T.SIZE_BODY`` (int) — keep these names alive,
# pointing at the corporate-blue preset.
#
# New code should prefer ``self._theme.*`` so theme switching propagates.

# CSS hex strings (with leading #)
PRIMARY = CORPORATE_BLUE.css_primary
SECONDARY = CORPORATE_BLUE.css_secondary
ACCENT = CORPORATE_BLUE.css_accent
POSITIVE = CORPORATE_BLUE.css_positive
NEGATIVE = CORPORATE_BLUE.css_negative
NEUTRAL = CORPORATE_BLUE.css_neutral
BG_LIGHT = CORPORATE_BLUE.css_bg_light
WHITE = CORPORATE_BLUE.css_white
TEXT_DARK = CORPORATE_BLUE.css_text_dark

# RGB tuples
RGB_PRIMARY = CORPORATE_BLUE.primary
RGB_SECONDARY = CORPORATE_BLUE.secondary
RGB_ACCENT = CORPORATE_BLUE.accent
RGB_POSITIVE = CORPORATE_BLUE.positive
RGB_NEGATIVE = CORPORATE_BLUE.negative
RGB_NEUTRAL = CORPORATE_BLUE.neutral
RGB_BG_LIGHT = CORPORATE_BLUE.bg_light
RGB_WHITE = CORPORATE_BLUE.white
RGB_TEXT_DARK = CORPORATE_BLUE.text_dark

# Fonts
FONT_CN = CORPORATE_BLUE.font_cn
FONT_NUM = CORPORATE_BLUE.font_num

# Font sizes
SIZE_TITLE = CORPORATE_BLUE.size_title
SIZE_H1 = CORPORATE_BLUE.size_h1
SIZE_H2 = CORPORATE_BLUE.size_h2
SIZE_H3 = CORPORATE_BLUE.size_h3
SIZE_BODY = CORPORATE_BLUE.size_body
SIZE_SMALL = CORPORATE_BLUE.size_small
SIZE_KPI_LARGE = CORPORATE_BLUE.size_kpi_large
SIZE_KPI_LABEL = CORPORATE_BLUE.size_kpi_label
SIZE_TABLE_HEADER = CORPORATE_BLUE.size_table_header
SIZE_TABLE_BODY = CORPORATE_BLUE.size_table_body

# Slide dimensions
SLIDE_WIDTH = CORPORATE_BLUE.slide_width
SLIDE_HEIGHT = CORPORATE_BLUE.slide_height

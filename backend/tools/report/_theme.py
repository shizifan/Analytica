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


ThemeName = Literal["corporate-blue", "liangang-journal"]


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

    def __post_init__(self):
        if not self.font_display:
            object.__setattr__(self, "font_display", self.font_cn)
        if not self.font_ui:
            object.__setattr__(self, "font_ui", self.font_cn)

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
    # 辽港数据期刊 PR-1 — 扩展字体 token（默认空串由 __post_init__ fallback）
    font_display: str = ""
    font_ui: str = ""
    font_cn_fallbacks: tuple[str, ...] = ()
    font_ui_fallbacks: tuple[str, ...] = ()
    font_mono_fallbacks: tuple[str, ...] = ()

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


# ── 辽港数据期刊 (Liangang Data Journal) — PR-1 注册，PR-2 切为默认 ──

LIANGANG_JOURNAL = Theme(
    name="liangang-journal",
    # 品牌基色：辽港集团 VI 手册 (PANTONE 293 C + 872 U)
    primary=(0x00, 0x48, 0x89),          # 辽港深蓝 #004889
    secondary=(0x33, 0x6E, 0xA4),       # navy 70% tint #336EA4
    accent=(0xAC, 0x91, 0x6B),          # 辽港古铜 #AC916B
    positive=(0x00, 0x48, 0x89),        # 上涨语义 = 主色
    negative=(0x8B, 0x4A, 0x2B),        # 下跌语义 = 古铜加深 #8B4A2B
    neutral=(0x9A, 0x8E, 0x78),         # ink_3 #9A8E78
    bg_light=(0xFB, 0xF6, 0xEE),        # paper 纸色 #FBF6EE
    white=(0xFF, 0xFE, 0xFB),
    text_dark=(0x1F, 0x1A, 0x12),       # ink_1 暖黑 #1F1A12
    # 字体
    font_cn="Noto Serif SC",
    font_num="JetBrains Mono",
    font_display="Noto Serif SC",
    font_ui="Noto Sans SC",
    font_cn_fallbacks=(
        "Source Han Serif SC", "Songti SC", "STSong", "SimSun",
    ),
    font_ui_fallbacks=(
        "PingFang SC", "Microsoft YaHei", "SimHei",
    ),
    font_mono_fallbacks=(
        "IBM Plex Mono", "Consolas", "Menlo", "Courier New",
    ),
    # 字号（pt）
    size_title=32,
    size_h1=22,
    size_h2=16,
    size_h3=14,
    size_body=11,
    size_small=9,
    size_kpi_large=28,
    size_kpi_label=8,
    size_table_header=9,
    size_table_body=10,
    # 16:9 slide（PPTX）
    slide_width=13.333,
    slide_height=7.5,
    # 图表色板
    chart_colors=(
        "004889", "AC916B", "80A4C2", "CFAB79", "336EA4", "8B4A2B",
    ),
    # 封面使用纸色背景 + navy 标题
    cover_bg=(0xFB, 0xF6, 0xEE),
    cover_text=(0x00, 0x48, 0x89),
)


THEMES: dict[str, Theme] = {
    "corporate-blue": CORPORATE_BLUE,
    "liangang-journal": LIANGANG_JOURNAL,
}


def get_theme(name: str | None = None) -> Theme:
    """Return a Theme by name, defaulting to ``liangang-journal``.

    Unknown names degrade silently to the default — matches the
    LLM-failure-fallback ethos in ``_outline_planner``: never break
    rendering for a misconfigured theme.
    """
    if name is None:
        return LIANGANG_JOURNAL
    return THEMES.get(name, LIANGANG_JOURNAL)


# ---------------------------------------------------------------------------
# Module-level constants — backward compatibility shim
# ---------------------------------------------------------------------------
# Existing renderer code uses ``from backend.tools.report import _theme as T``
# and reads ``T.PRIMARY`` (CSS hex string with #), ``T.RGB_PRIMARY`` (tuple),
# ``T.FONT_CN`` (string), ``T.SIZE_BODY`` (int) — keep these names alive,
# pointing at the liangang-journal preset (the new default).
#
# New code should prefer ``self._theme.*`` so theme switching propagates.

# CSS hex strings (with leading #)
PRIMARY = LIANGANG_JOURNAL.css_primary
SECONDARY = LIANGANG_JOURNAL.css_secondary
ACCENT = LIANGANG_JOURNAL.css_accent
POSITIVE = LIANGANG_JOURNAL.css_positive
NEGATIVE = LIANGANG_JOURNAL.css_negative
NEUTRAL = LIANGANG_JOURNAL.css_neutral
BG_LIGHT = LIANGANG_JOURNAL.css_bg_light
WHITE = LIANGANG_JOURNAL.css_white
TEXT_DARK = LIANGANG_JOURNAL.css_text_dark

# RGB tuples
RGB_PRIMARY = LIANGANG_JOURNAL.primary
RGB_SECONDARY = LIANGANG_JOURNAL.secondary
RGB_ACCENT = LIANGANG_JOURNAL.accent
RGB_POSITIVE = LIANGANG_JOURNAL.positive
RGB_NEGATIVE = LIANGANG_JOURNAL.negative
RGB_NEUTRAL = LIANGANG_JOURNAL.neutral
RGB_BG_LIGHT = LIANGANG_JOURNAL.bg_light
RGB_WHITE = LIANGANG_JOURNAL.white
RGB_TEXT_DARK = LIANGANG_JOURNAL.text_dark

# Fonts
FONT_CN = LIANGANG_JOURNAL.font_cn
FONT_NUM = LIANGANG_JOURNAL.font_num
FONT_DISPLAY = LIANGANG_JOURNAL.font_display
FONT_UI = LIANGANG_JOURNAL.font_ui

# Font sizes
SIZE_TITLE = LIANGANG_JOURNAL.size_title
SIZE_H1 = LIANGANG_JOURNAL.size_h1
SIZE_H2 = LIANGANG_JOURNAL.size_h2
SIZE_H3 = LIANGANG_JOURNAL.size_h3
SIZE_BODY = LIANGANG_JOURNAL.size_body
SIZE_SMALL = LIANGANG_JOURNAL.size_small
SIZE_KPI_LARGE = LIANGANG_JOURNAL.size_kpi_large
SIZE_KPI_LABEL = LIANGANG_JOURNAL.size_kpi_label
SIZE_TABLE_HEADER = LIANGANG_JOURNAL.size_table_header
SIZE_TABLE_BODY = LIANGANG_JOURNAL.size_table_body

# Slide dimensions
SLIDE_WIDTH = LIANGANG_JOURNAL.slide_width
SLIDE_HEIGHT = LIANGANG_JOURNAL.slide_height

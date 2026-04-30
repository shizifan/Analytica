"""Phase 1 — Theme system tests.

Covers:
- Theme dataclass field defaults (Phase 4-5 forward-compat)
- ``get_theme`` returns corporate-blue by default + on unknown name
- Module-level legacy constants stay aligned with the default preset
- Hex / CSS string accessors round-trip with RGB tuples
- Frozen instance: mutation raises FrozenInstanceError
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from backend.tools.report import _theme as T
from backend.tools.report._theme import (
    CORPORATE_BLUE,
    THEMES,
    Theme,
    _hex_to_rgb,
    _rgb_to_hex,
    get_theme,
)

pytestmark = pytest.mark.contract


# ---------------------------------------------------------------------------
# Default selection
# ---------------------------------------------------------------------------

def test_get_theme_with_no_arg_returns_corporate_blue():
    assert get_theme() is CORPORATE_BLUE
    assert get_theme().name == "corporate-blue"


def test_get_theme_with_none_returns_corporate_blue():
    assert get_theme(None) is CORPORATE_BLUE


def test_get_theme_with_known_name_returns_preset():
    assert get_theme("corporate-blue") is CORPORATE_BLUE


def test_get_theme_with_unknown_name_falls_back_silently():
    """Misconfigured theme names must not break rendering."""
    assert get_theme("tech-gray-not-yet-implemented") is CORPORATE_BLUE
    assert get_theme("") is CORPORATE_BLUE


def test_themes_dict_contains_corporate_blue():
    assert "corporate-blue" in THEMES
    assert THEMES["corporate-blue"] is CORPORATE_BLUE


# ---------------------------------------------------------------------------
# Theme dataclass invariants
# ---------------------------------------------------------------------------

def test_theme_is_frozen():
    with pytest.raises(FrozenInstanceError):
        CORPORATE_BLUE.primary = (0, 0, 0)  # type: ignore[misc]


def test_corporate_blue_has_all_required_fields():
    """Smoke check that all dataclass fields are populated. Catches
    accidentally adding a field without supplying a default."""
    expected_color_attrs = (
        "primary", "secondary", "accent", "positive", "negative",
        "neutral", "bg_light", "white", "text_dark",
    )
    for attr in expected_color_attrs:
        rgb = getattr(CORPORATE_BLUE, attr)
        assert isinstance(rgb, tuple) and len(rgb) == 3
        for c in rgb:
            assert 0 <= c <= 255


def test_corporate_blue_phase4_defaults_present():
    """Phase 4-5 fields default to sensible values so old presets stay
    valid without retro-fitting all colors."""
    assert isinstance(CORPORATE_BLUE.chart_colors, tuple)
    assert len(CORPORATE_BLUE.chart_colors) >= 4
    for hex_str in CORPORATE_BLUE.chart_colors:
        assert "#" not in hex_str  # 6-digit hex without leading #
        assert len(hex_str) == 6
    assert isinstance(CORPORATE_BLUE.callout_warn_bg, tuple)
    assert isinstance(CORPORATE_BLUE.callout_info_bg, tuple)
    assert CORPORATE_BLUE.radius_card > 0
    assert 0.0 <= CORPORATE_BLUE.shadow_strength <= 1.0


# ---------------------------------------------------------------------------
# Color accessors
# ---------------------------------------------------------------------------

def test_hex_accessors_match_rgb_tuples():
    assert CORPORATE_BLUE.hex_primary == _rgb_to_hex(CORPORATE_BLUE.primary)
    assert CORPORATE_BLUE.hex_accent == _rgb_to_hex(CORPORATE_BLUE.accent)
    assert CORPORATE_BLUE.hex_positive == _rgb_to_hex(CORPORATE_BLUE.positive)


def test_css_accessors_have_hash_prefix():
    assert CORPORATE_BLUE.css_primary.startswith("#")
    assert CORPORATE_BLUE.css_primary == "#" + CORPORATE_BLUE.hex_primary


def test_hex_helpers_round_trip():
    rgb = (0x1E, 0x3A, 0x5F)
    assert _hex_to_rgb(_rgb_to_hex(rgb)) == rgb
    assert _hex_to_rgb("#1E3A5F") == rgb  # accepts # prefix
    assert _hex_to_rgb("1e3a5f") == rgb   # case-insensitive


def test_cover_bg_defaults_to_primary_when_unset():
    # corporate-blue leaves cover_bg=None → falls back to primary
    assert CORPORATE_BLUE.cover_bg is None
    assert CORPORATE_BLUE.hex_cover_bg == CORPORATE_BLUE.hex_primary
    assert CORPORATE_BLUE.cover_text is None
    assert CORPORATE_BLUE.hex_cover_text == CORPORATE_BLUE.hex_white


def test_cover_bg_uses_explicit_value_when_set():
    custom = Theme(
        name="custom",
        primary=(0, 0, 0),
        secondary=(0, 0, 0),
        accent=(0, 0, 0),
        positive=(0, 0, 0),
        negative=(0, 0, 0),
        neutral=(0, 0, 0),
        bg_light=(0, 0, 0),
        white=(0xFF, 0xFF, 0xFF),
        text_dark=(0, 0, 0),
        font_cn="x", font_num="y",
        size_title=10, size_h1=10, size_h2=10, size_h3=10,
        size_body=10, size_small=10, size_kpi_large=10,
        size_kpi_label=10, size_table_header=10, size_table_body=10,
        slide_width=10, slide_height=7.5,
        cover_bg=(0xAB, 0xCD, 0xEF),
        cover_text=(0x12, 0x34, 0x56),
    )
    assert custom.hex_cover_bg == "ABCDEF"
    assert custom.hex_cover_text == "123456"


# ---------------------------------------------------------------------------
# Module-level legacy constants
# ---------------------------------------------------------------------------

def test_module_constants_match_default_preset():
    """Existing renderer code uses ``T.PRIMARY`` / ``T.RGB_PRIMARY`` /
    ``T.FONT_CN`` etc. — those names must still equal the corporate-blue
    preset values so baseline output is byte-equivalent post-refactor."""
    assert T.PRIMARY == CORPORATE_BLUE.css_primary
    assert T.SECONDARY == CORPORATE_BLUE.css_secondary
    assert T.ACCENT == CORPORATE_BLUE.css_accent
    assert T.POSITIVE == CORPORATE_BLUE.css_positive
    assert T.NEGATIVE == CORPORATE_BLUE.css_negative

    assert T.RGB_PRIMARY == CORPORATE_BLUE.primary
    assert T.RGB_ACCENT == CORPORATE_BLUE.accent
    assert T.RGB_BG_LIGHT == CORPORATE_BLUE.bg_light

    assert T.FONT_CN == CORPORATE_BLUE.font_cn
    assert T.FONT_NUM == CORPORATE_BLUE.font_num

    assert T.SIZE_TITLE == CORPORATE_BLUE.size_title
    assert T.SIZE_BODY == CORPORATE_BLUE.size_body
    assert T.SIZE_KPI_LARGE == CORPORATE_BLUE.size_kpi_large

    assert T.SLIDE_WIDTH == CORPORATE_BLUE.slide_width
    assert T.SLIDE_HEIGHT == CORPORATE_BLUE.slide_height


# ---------------------------------------------------------------------------
# Renderer integration
# ---------------------------------------------------------------------------

def test_block_renderer_base_defaults_to_corporate_blue():
    from backend.tools.report._block_renderer import BlockRendererBase

    class _Subclass(BlockRendererBase):
        pass

    r = _Subclass()
    assert r._theme is CORPORATE_BLUE


def test_block_renderer_base_accepts_explicit_theme():
    from backend.tools.report._block_renderer import BlockRendererBase

    class _Subclass(BlockRendererBase):
        pass

    custom = get_theme("corporate-blue")  # use known-good preset for safety
    r = _Subclass(theme=custom)
    assert r._theme is custom


@pytest.mark.parametrize("renderer_cls_path", [
    "backend.tools.report._renderers.markdown.MarkdownBlockRenderer",
    "backend.tools.report._renderers.docx.DocxBlockRenderer",
    "backend.tools.report._renderers.pptx.PptxBlockRenderer",
    "backend.tools.report._renderers.html.HtmlBlockRenderer",
    "backend.tools.report._renderers.pptxgen.PptxGenJSBlockRenderer",
])
def test_concrete_renderers_accept_theme_kwarg(renderer_cls_path):
    """All five concrete BlockRenderer implementations must accept the
    ``theme`` kwarg added in Phase 1.2."""
    import importlib

    module_path, cls_name = renderer_cls_path.rsplit(".", 1)
    cls = getattr(importlib.import_module(module_path), cls_name)
    r = cls(theme=CORPORATE_BLUE)
    assert r._theme is CORPORATE_BLUE


def test_concrete_renderers_default_theme_when_omitted():
    """Constructing without ``theme=`` falls back to corporate-blue —
    keeps existing test fixtures and direct callers working."""
    from backend.tools.report._renderers.markdown import MarkdownBlockRenderer
    r = MarkdownBlockRenderer()
    assert r._theme is CORPORATE_BLUE


# ---------------------------------------------------------------------------
# Trend tokens (Phase 4.3)
# ---------------------------------------------------------------------------

def test_trend_arrow_returns_glyph_for_known_tokens():
    from backend.tools.report._theme import trend_arrow

    assert trend_arrow("positive") == "↑"
    assert trend_arrow("negative") == "↓"
    assert trend_arrow("flat") == "→"


def test_trend_arrow_returns_empty_for_unknown():
    from backend.tools.report._theme import trend_arrow

    assert trend_arrow(None) == ""
    assert trend_arrow("") == ""
    assert trend_arrow("rising") == ""


def test_trend_rgb_resolves_against_theme():
    from backend.tools.report._theme import trend_rgb

    assert trend_rgb("positive") == CORPORATE_BLUE.positive
    assert trend_rgb("negative") == CORPORATE_BLUE.negative
    assert trend_rgb("flat") == CORPORATE_BLUE.neutral
    # Unknown / None → neutral fallback
    assert trend_rgb(None) == CORPORATE_BLUE.neutral
    assert trend_rgb("rising") == CORPORATE_BLUE.neutral


def test_trend_for_value_classifies_signs():
    from backend.tools.report._theme import trend_for_value

    assert trend_for_value(0.12) == "positive"
    assert trend_for_value(-0.05) == "negative"
    assert trend_for_value(0) == "flat"
    assert trend_for_value(None) == "flat"


def test_trend_tokens_keys_aligned_with_theme_fields():
    """Every TREND_TOKENS color_attr must correspond to a real Theme field
    so renderers can read it via ``getattr``."""
    from backend.tools.report._theme import TREND_TOKENS

    for token, spec in TREND_TOKENS.items():
        assert hasattr(CORPORATE_BLUE, spec["color_attr"]), (
            f"trend '{token}' references missing Theme attribute "
            f"'{spec['color_attr']}'"
        )
        # css_attr also lives on Theme (as a property)
        assert hasattr(CORPORATE_BLUE, spec["css_attr"])

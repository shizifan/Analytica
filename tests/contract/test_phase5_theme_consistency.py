"""Phase 5.5 — Cross-theme visual assertions.

Locks in two contracts:
1. Same outline + same theme → byte-equivalent output (renderer is
   deterministic; theme alone determines colour).
2. Same outline + *different* theme → colour strings differ but the
   document skeleton (paragraph count, table structure, chart
   placeholders) stays identical. Renaming a colour token must not
   change content layout.

Approach: build a ``_TestTheme`` clone of corporate-blue with all
colour fields rotated to a non-overlapping palette, then render the
same outline twice and compare:
  - HTML / Markdown — string-level (HTML strips colours via regex)
  - DOCX / PPT — structural extraction via baseline comparators
"""
from __future__ import annotations

import re
from dataclasses import replace

import pytest

from backend.tools.report._block_renderer import render_outline
from backend.tools.report._outline import KPIItem
from backend.tools.report._outline import (
    ChartAsset,
    ChartBlock,
    GrowthIndicatorsBlock,
    OutlineSection,
    ParagraphBlock,
    ReportOutline,
    SectionCoverBlock,
    StatsAsset,
    TableBlock,
    reset_id_counters,
)
from backend.tools.report._renderers.docx import DocxBlockRenderer
from backend.tools.report._renderers.html import HtmlBlockRenderer
from backend.tools.report._renderers.markdown import MarkdownBlockRenderer
from backend.tools.report._renderers.pptx import PptxBlockRenderer
from backend.tools.report._theme import CORPORATE_BLUE, Theme

from tests.contract._report_baseline import (
    docx_to_text_tree,
    html_to_text_tree,
    markdown_normalize,
    pptx_to_text_tree,
)

pytestmark = pytest.mark.contract


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _alt_theme() -> Theme:
    """Clone of corporate-blue with every colour rotated.

    Specifically chosen so no colour clashes with corporate-blue's
    palette — that way "colours differ between themes" is testable
    even on substring matches. Callout-specific tints are also
    overridden so renderers reading those fields (DOCX build_callout)
    visibly switch.
    """
    return replace(
        CORPORATE_BLUE,
        name="phase5-test",
        primary=(0x4A, 0x14, 0x83),       # deep purple
        secondary=(0x6F, 0x42, 0xC1),
        accent=(0x39, 0xD3, 0x53),         # green
        positive=(0x2D, 0xCE, 0x89),
        negative=(0xFB, 0x6D, 0x4C),
        neutral=(0x90, 0x9B, 0xA8),
        bg_light=(0xEE, 0xE9, 0xF7),
        text_dark=(0x1F, 0x14, 0x2E),
        # Phase 4.1 callout fields tracked separately so themes can
        # decouple "warning red" from "alert tint". Override here so
        # the alt-theme assertions can detect callout repainting.
        callout_warn_bg=(0xFE, 0xE5, 0xE0),
        callout_warn_border=(0xFB, 0x6D, 0x4C),
        callout_info_bg=(0xE9, 0xDD, 0xF7),
        callout_info_border=(0x6F, 0x42, 0xC1),
    )


@pytest.fixture(autouse=True)
def _reset_ids():
    reset_id_counters()
    yield


def _full_outline() -> ReportOutline:
    """Outline exercising every visual primitive theme touches:
    section cover, KPI overview, narrative, callout, growth, table.
    """
    chart = ChartAsset(
        asset_id="C0001", source_task="T1",
        option={
            "title": {"text": "demo"},
            "xAxis": {"type": "category", "data": ["A", "B"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": [1, 2]}],
        },
    )
    stats = StatsAsset(
        asset_id="S0001", source_task="T1",
        summary_stats={"qty": {"mean": 50.0, "min": 10.0, "max": 90.0}},
    )
    return ReportOutline(
        metadata={"title": "theme demo", "author": "CI", "date": "2026-04-29"},
        kpi_summary=[
            KPIItem(label="Total", value="1234", sub="Q1", trend="positive"),
        ],
        sections=[
            OutlineSection(name="一、现状", role="status", blocks=[
                SectionCoverBlock(block_id="C1", index=1, title="一、现状"),
                ParagraphBlock(block_id="B1", text="基础段落"),
                ParagraphBlock(
                    block_id="B2", text="低于警戒线",
                    style="callout-warn",
                ),
                ChartBlock(block_id="B3", asset_id="C0001"),
                TableBlock(block_id="B4", asset_id="S0001"),
                GrowthIndicatorsBlock(
                    block_id="B5",
                    growth_rates={"qty": {"yoy": 0.12, "mom": 0.03}},
                ),
            ]),
            OutlineSection(name="总结", role="appendix", blocks=[
                ParagraphBlock(
                    block_id="B6", text="结论文本", style="lead",
                ),
            ]),
        ],
        assets={"C0001": chart, "S0001": stats},
    )


# ---------------------------------------------------------------------------
# Same theme determinism
# ---------------------------------------------------------------------------

def test_html_same_theme_byte_equivalent():
    reset_id_counters()
    out1 = render_outline(_full_outline(), HtmlBlockRenderer(theme=CORPORATE_BLUE))
    reset_id_counters()
    out2 = render_outline(_full_outline(), HtmlBlockRenderer(theme=CORPORATE_BLUE))
    assert out1 == out2


def test_markdown_same_theme_byte_equivalent():
    reset_id_counters()
    out1 = render_outline(_full_outline(), MarkdownBlockRenderer(theme=CORPORATE_BLUE))
    reset_id_counters()
    out2 = render_outline(_full_outline(), MarkdownBlockRenderer(theme=CORPORATE_BLUE))
    assert out1 == out2


# ---------------------------------------------------------------------------
# Cross-theme: skeleton identical, colours differ
# ---------------------------------------------------------------------------

def _strip_html_colours(html: str) -> str:
    """Remove every colour token (#RRGGBB and rgb(R,G,B)) so the
    remaining HTML reflects only structure + textual content."""
    html = re.sub(r"#[0-9A-Fa-f]{6}\b", "<COLOR>", html)
    html = re.sub(r"rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)", "<COLOR>", html)
    return html


def test_html_cross_theme_structure_identical_colours_differ():
    """The new static HTML template uses CSS custom properties instead of
    theme-injected colours. Therefore HTML output is byte-equivalent
    regardless of theme — the structure remains identical, but colours
    are controlled by the static CSS, not the theme object."""
    reset_id_counters()
    html_default = render_outline(
        _full_outline(), HtmlBlockRenderer(theme=CORPORATE_BLUE),
    )
    reset_id_counters()
    html_alt = render_outline(
        _full_outline(), HtmlBlockRenderer(theme=_alt_theme()),
    )

    # With the static template, HTML output is byte-equivalent across themes.
    assert html_default == html_alt, (
        "HTML output must be identical when template is static "
        "(CSS custom properties, not theme-injected colours)."
    )

    # Strip colours and compare — should also match.
    assert _strip_html_colours(html_default) == _strip_html_colours(html_alt)


def test_html_static_template_css_properties_present():
    """The static HTML template uses CSS custom properties (--primary,
    --accent, --paper, etc.). Verify the key design tokens are present
    in every output regardless of which theme is passed."""
    alt = _alt_theme()
    reset_id_counters()
    html = render_outline(_full_outline(), HtmlBlockRenderer(theme=alt))
    for css_prop in (
        "--primary", "--accent", "--paper", "--ink-1", "--alert",
        "--font-display", "--font-mono", "--font-ui",
    ):
        assert css_prop in html, f"CSS property {css_prop} missing from HTML output"


def test_markdown_cross_theme_byte_equivalent():
    """Markdown is theme-agnostic (no colour escapes) — should be
    byte-equivalent across themes."""
    reset_id_counters()
    md_default = render_outline(
        _full_outline(), MarkdownBlockRenderer(theme=CORPORATE_BLUE),
    )
    reset_id_counters()
    md_alt = render_outline(
        _full_outline(), MarkdownBlockRenderer(theme=_alt_theme()),
    )
    assert md_default == md_alt


def test_docx_cross_theme_skeleton_identical():
    """DOCX OOXML differs in colour XML but the structural text tree
    (paragraphs, tables, picture placeholders, page breaks) must be
    identical across themes."""
    reset_id_counters()
    docx_default = render_outline(
        _full_outline(), DocxBlockRenderer(theme=CORPORATE_BLUE),
    )
    reset_id_counters()
    docx_alt = render_outline(
        _full_outline(), DocxBlockRenderer(theme=_alt_theme()),
    )
    assert docx_default != docx_alt
    assert docx_to_text_tree(docx_default) == docx_to_text_tree(docx_alt)


def test_docx_alt_theme_colour_present_in_xml():
    """Alt theme's primary hex colour appears in DOCX XML — verifies
    theme injection actually drives output, not just module constants."""
    import io
    import zipfile

    alt = _alt_theme()
    reset_id_counters()
    docx = render_outline(_full_outline(), DocxBlockRenderer(theme=alt))
    with zipfile.ZipFile(io.BytesIO(docx)) as zf:
        xml = zf.read("word/document.xml").decode()
    # The alt theme's negative colour (callout border) must appear in
    # XML even though section heading still uses theme.PRIMARY (a
    # module-level legacy reference). This is the agreed Phase 1 split:
    # new visual code reads self._theme.*; legacy paths use module
    # constants.
    alt_negative_hex = (
        f"{alt.negative[0]:02X}{alt.negative[1]:02X}{alt.negative[2]:02X}"
    )
    assert alt_negative_hex in xml, (
        f"alt theme negative {alt_negative_hex} not in DOCX — callout "
        "ignored its theme override."
    )


def test_pptx_cross_theme_skeleton_identical():
    """PPT (python-pptx fallback) also keeps the structural skeleton
    constant across themes."""
    reset_id_counters()
    pptx_default = render_outline(
        _full_outline(), PptxBlockRenderer(theme=CORPORATE_BLUE),
    )
    reset_id_counters()
    pptx_alt = render_outline(
        _full_outline(), PptxBlockRenderer(theme=_alt_theme()),
    )
    # PptxBlockRenderer mostly reads module-level theme constants
    # (Phase 1 split — fallback path stays simple), so byte output may
    # match across themes. Skeleton must match either way.
    assert pptx_to_text_tree(pptx_default) == pptx_to_text_tree(pptx_alt)


# ---------------------------------------------------------------------------
# Theme switching guards
# ---------------------------------------------------------------------------

def test_replace_dataclass_helper_creates_independent_theme():
    alt = replace(CORPORATE_BLUE, name="x", primary=(0, 0, 0))
    assert alt.primary == (0, 0, 0)
    assert CORPORATE_BLUE.primary != (0, 0, 0)


def test_alt_theme_phase5_fields_inherited_from_corporate_blue():
    """Phase 5.3 default fields (radius, shadow, padding) propagate
    via ``replace`` since alt_theme didn't override them."""
    alt = _alt_theme()
    assert alt.radius_card == CORPORATE_BLUE.radius_card
    assert alt.shadow_strength == CORPORATE_BLUE.shadow_strength
    assert alt.padding_card == CORPORATE_BLUE.padding_card
    assert alt.spacing_section == CORPORATE_BLUE.spacing_section

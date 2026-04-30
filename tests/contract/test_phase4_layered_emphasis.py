"""Phase 4 — layered emphasis tests.

Locks in the cross-backend contract for callout / table-highlight /
trend / data-label features so future visual polish can't quietly
regress them.
"""
from __future__ import annotations

import pytest

from backend.tools.report._block_renderer import render_outline
from backend.tools.report._outline import (
    OutlineSection,
    ParagraphBlock,
    ReportOutline,
    TableAsset,
    TableBlock,
    reset_id_counters,
)
from backend.tools.report._renderers.docx import DocxBlockRenderer
from backend.tools.report._renderers.html import HtmlBlockRenderer
from backend.tools.report._renderers.markdown import MarkdownBlockRenderer
from backend.tools.report._renderers.pptx import PptxBlockRenderer
from backend.tools.report._table_highlight import (
    resolve_cell_highlights,
    resolve_color,
)
from backend.tools.report._theme import (
    CORPORATE_BLUE,
    TREND_TOKENS,
    trend_arrow,
    trend_for_value,
    trend_rgb,
)

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def _reset_ids():
    reset_id_counters()
    yield


# ---------------------------------------------------------------------------
# Phase 4.1 — Callout style propagation
# ---------------------------------------------------------------------------

def _outline_with_callouts() -> ReportOutline:
    return ReportOutline(
        metadata={"title": "callout demo", "author": "", "date": ""},
        sections=[
            OutlineSection(
                name="风险评估", role="attribution",
                blocks=[
                    ParagraphBlock(block_id="B1", text="正常文字", style="body"),
                    ParagraphBlock(
                        block_id="B2",
                        text="设备完好率下降至 82%",
                        style="callout-warn",
                    ),
                    ParagraphBlock(
                        block_id="B3",
                        text="建议关注 Q2",
                        style="callout-info",
                    ),
                ],
            ),
            OutlineSection(name="总结", role="appendix", blocks=[]),
        ],
    )


def test_markdown_callout_warn_renders_blockquote_with_warning_emoji():
    md = render_outline(_outline_with_callouts(), MarkdownBlockRenderer())
    assert "> ⚠️ **注意**：设备完好率下降至 82%" in md


def test_markdown_callout_info_renders_blockquote_with_lightbulb():
    md = render_outline(_outline_with_callouts(), MarkdownBlockRenderer())
    assert "> 💡 建议关注 Q2" in md


def test_html_callout_warn_uses_warn_class():
    html = render_outline(_outline_with_callouts(), HtmlBlockRenderer())
    assert '<div class="callout warn">设备完好率下降至 82%</div>' in html


def test_html_callout_info_uses_info_class():
    html = render_outline(_outline_with_callouts(), HtmlBlockRenderer())
    assert '<div class="callout info">建议关注 Q2</div>' in html


def test_html_includes_callout_css_with_theme_colors():
    html = render_outline(_outline_with_callouts(), HtmlBlockRenderer())
    # Border colour must come from theme negative for warn callouts
    assert CORPORATE_BLUE.css_negative in html
    # Info border uses secondary
    assert CORPORATE_BLUE.css_secondary in html


def test_docx_callout_warn_emits_left_border_and_shading():
    import io
    import zipfile

    docx = render_outline(_outline_with_callouts(), DocxBlockRenderer())
    with zipfile.ZipFile(io.BytesIO(docx)) as zf:
        xml = zf.read("word/document.xml").decode()
    # Border XML and theme negative colour both present
    assert "<w:pBdr" in xml
    assert "C62828" in xml  # theme.negative hex
    # Info callout fills with light blue (callout_info_bg default)
    assert "E3F2FD" in xml


def test_pptx_callout_prefix_emoji_in_buffered_text():
    """Buffer-mode PPT prepends emoji to narrative text so the value
    survives ``end_section`` flush into the narrative slide."""
    import io
    import zipfile

    pptx = render_outline(_outline_with_callouts(), PptxBlockRenderer())
    with zipfile.ZipFile(io.BytesIO(pptx)) as zf:
        slides_xml = "".join(
            zf.read(n).decode()
            for n in zf.namelist()
            if n.startswith("ppt/slides/slide") and n.endswith(".xml")
        )
    assert "⚠ 注意: 设备完好率下降至 82%" in slides_xml
    assert "💡 提示: 建议关注 Q2" in slides_xml


# ---------------------------------------------------------------------------
# Phase 4.2 — TableBlock.highlight_rules
# ---------------------------------------------------------------------------

def test_resolve_color_maps_semantic_tokens_to_theme():
    assert resolve_color("positive", CORPORATE_BLUE) == CORPORATE_BLUE.positive
    assert resolve_color("negative", CORPORATE_BLUE) == CORPORATE_BLUE.negative
    assert resolve_color("accent", CORPORATE_BLUE) == CORPORATE_BLUE.accent


def test_resolve_color_metallics_have_fixed_values():
    assert resolve_color("gold", CORPORATE_BLUE) == (0xFF, 0xD7, 0x00)
    assert resolve_color("silver", CORPORATE_BLUE) == (0xC0, 0xC0, 0xC0)
    assert resolve_color("bronze", CORPORATE_BLUE) == (0xCD, 0x7F, 0x32)


def test_resolve_color_unknown_returns_none():
    assert resolve_color("magenta", CORPORATE_BLUE) is None
    assert resolve_color(None, CORPORATE_BLUE) is None
    assert resolve_color("", CORPORATE_BLUE) is None


def test_whole_column_rule_paints_all_body_cells():
    cells = resolve_cell_highlights(
        headers=["问题", "原因", "影响"],
        n_rows=3,
        rules=[{"col": "原因", "color": "negative"}],
        theme=CORPORATE_BLUE,
    )
    # 3 body rows × col_idx=1 (原因)
    assert {(0, 1), (1, 1), (2, 1)} == set(cells.keys())
    assert cells[(0, 1)] == CORPORATE_BLUE.negative


def test_whole_row_rule_paints_all_columns():
    cells = resolve_cell_highlights(
        headers=["A", "B", "C"],
        n_rows=2,
        rules=[{"row": 1, "color": "gold"}],
        theme=CORPORATE_BLUE,
    )
    assert {(1, 0), (1, 1), (1, 2)} == set(cells.keys())


def test_intersection_rule_paints_single_cell():
    cells = resolve_cell_highlights(
        headers=["A", "B"], n_rows=2,
        rules=[{"col": "B", "row": 0, "color": "accent"}],
        theme=CORPORATE_BLUE,
    )
    assert cells == {(0, 1): CORPORATE_BLUE.accent}


def test_invalid_rules_silently_skipped():
    cells = resolve_cell_highlights(
        headers=["A"], n_rows=1,
        rules=[
            {"col": "Z", "color": "negative"},   # unknown column
            {"row": 99, "color": "gold"},        # out of range
            {"color": "negative"},                # neither col nor row
            {"col": "A", "color": "magenta"},     # unknown color
            "garbage",                            # not a dict
        ],
        theme=CORPORATE_BLUE,
    )
    assert cells == {}


def _outline_with_highlight_table() -> ReportOutline:
    table = TableAsset(
        asset_id="T0001", source_task="T1",
        df_records=[
            {"问题": "A", "原因": "x", "影响": "y"},
            {"问题": "B", "原因": "z", "影响": "w"},
        ],
        columns_meta=[],
    )
    return ReportOutline(
        metadata={"title": "demo", "author": "", "date": ""},
        sections=[
            OutlineSection(
                name="归因", role="attribution",
                blocks=[
                    TableBlock(
                        block_id="B1", asset_id="T0001",
                        caption="归因汇总",
                        highlight_rules=[
                            {"col": "原因", "color": "negative"},
                            {"row": 1, "color": "gold"},
                        ],
                    ),
                ],
            ),
            OutlineSection(name="总结", role="appendix", blocks=[]),
        ],
        assets={"T0001": table},
    )


def test_html_table_renders_cell_highlight_inline_styles():
    html = render_outline(_outline_with_highlight_table(), HtmlBlockRenderer())
    # negative red rgb
    assert "background:rgb(198,40,40)" in html
    # gold
    assert "background:rgb(255,215,0)" in html


def test_docx_table_applies_cell_shading():
    import io
    import zipfile

    docx = render_outline(_outline_with_highlight_table(), DocxBlockRenderer())
    with zipfile.ZipFile(io.BytesIO(docx)) as zf:
        xml = zf.read("word/document.xml").decode()
    assert 'w:fill="C62828"' in xml  # negative
    assert 'w:fill="FFD700"' in xml  # gold


# ---------------------------------------------------------------------------
# Phase 4.3 — Trend tokens
# ---------------------------------------------------------------------------

def test_trend_arrow_glyphs_are_distinct():
    arrows = {trend_arrow(t) for t in ("positive", "negative", "flat")}
    assert arrows == {"↑", "↓", "→"}


def test_trend_rgb_resolves_via_theme():
    assert trend_rgb("positive", CORPORATE_BLUE) == CORPORATE_BLUE.positive
    assert trend_rgb("negative", CORPORATE_BLUE) == CORPORATE_BLUE.negative


def test_trend_for_value_classifies_signs():
    assert trend_for_value(0.05) == "positive"
    assert trend_for_value(-0.05) == "negative"
    assert trend_for_value(0) == "flat"
    assert trend_for_value(None) == "flat"


def test_trend_tokens_attrs_present_on_theme():
    for token, spec in TREND_TOKENS.items():
        assert hasattr(CORPORATE_BLUE, spec["color_attr"])
        assert hasattr(CORPORATE_BLUE, spec["css_attr"])


# ---------------------------------------------------------------------------
# Phase 4.4 — Data labels in HTML
# ---------------------------------------------------------------------------

def test_html_single_series_bar_gets_top_label():
    out = HtmlBlockRenderer._enrich_option_for_html(
        {"series": [{"type": "bar", "data": [1, 2, 3]}]},
    )
    assert out["series"][0]["label"] == {"show": True, "position": "top"}


def test_html_horizontal_bar_label_on_right():
    out = HtmlBlockRenderer._enrich_option_for_html({
        "yAxis": {"type": "category", "data": ["A"]},
        "xAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [10]}],
    })
    assert out["series"][0]["label"] == {"show": True, "position": "right"}


def test_html_multi_series_bar_no_label():
    out = HtmlBlockRenderer._enrich_option_for_html({
        "series": [
            {"type": "bar", "data": [1]}, {"type": "bar", "data": [2]},
        ],
    })
    for s in out["series"]:
        assert "label" not in s


def test_html_user_supplied_label_preserved():
    user_label = {"show": True, "position": "inside"}
    out = HtmlBlockRenderer._enrich_option_for_html({
        "series": [{"type": "bar", "data": [1], "label": user_label}],
    })
    assert out["series"][0]["label"] is user_label


def test_html_enrichment_does_not_mutate_source():
    src = {"series": [{"type": "bar", "data": [1]}]}
    HtmlBlockRenderer._enrich_option_for_html(src)
    assert "label" not in src["series"][0]


# ---------------------------------------------------------------------------
# Phase 4.5 — Risk warning callout (verify Phase 4.1 covers the brief)
# ---------------------------------------------------------------------------

def test_callout_warn_includes_warning_emoji_across_backends():
    o = ReportOutline(
        metadata={"title": "x", "author": "", "date": ""},
        sections=[
            OutlineSection(name="风险", role="attribution", blocks=[
                ParagraphBlock(
                    block_id="B1", text="设备未达成", style="callout-warn",
                ),
            ]),
            OutlineSection(name="总结", role="appendix", blocks=[]),
        ],
    )
    md = render_outline(o, MarkdownBlockRenderer())
    html = render_outline(o, HtmlBlockRenderer())
    assert "⚠️" in md
    assert "callout warn" in html

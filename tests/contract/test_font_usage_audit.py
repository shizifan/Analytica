"""Phase 5.2 — Font separation audit.

Locks in the cross-backend font usage convention:
- 中文文字 (titles, narrative, labels) uses ``T.FONT_CN``
- 数字文字 (KPI values, table numeric cells, growth rates) uses
  ``T.FONT_NUM`` (typically a monospace face for column alignment)

The contract guards against accidental drift when a new visual feature
forgets to opt into ``font_num`` for numeric content.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from backend.tools.report import _theme as T
from backend.tools.report._block_renderer import render_outline
from backend.tools.report._outline import KPIItem
from backend.tools.report._outline import (
    OutlineSection,
    ReportOutline,
    SectionCoverBlock,
    TableAsset,
    TableBlock,
    reset_id_counters,
)
from backend.tools.report._renderers.docx import DocxBlockRenderer
from backend.tools.report._renderers.html import HtmlBlockRenderer
from backend.tools.report._theme import CORPORATE_BLUE, LIANGANG_JOURNAL

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def _reset_ids():
    reset_id_counters()
    yield


def _outline_with_kpi_and_table() -> ReportOutline:
    table = TableAsset(
        asset_id="T0001", source_task="T1",
        df_records=[
            {"port": "大连港", "qty": 4500.5},
            {"port": "营口港", "qty": 3200.1},
        ],
        columns_meta=[],
    )
    return ReportOutline(
        metadata={"title": "字体审计", "author": "CI", "date": "2026-04-29"},
        kpi_summary=[
            KPIItem(label="总吞吐量", value="9500.6 万吨",
                    sub="2026 Q1", trend="positive"),
        ],
        sections=[
            OutlineSection(name="一、现状", role="status", blocks=[
                SectionCoverBlock(
                    block_id="C1", index=1, title="一、现状",
                ),
                TableBlock(block_id="B1", asset_id="T0001", caption="数据"),
            ]),
            OutlineSection(name="总结", role="appendix", blocks=[]),
        ],
        assets={"T0001": table},
    )


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def test_docx_table_numeric_cells_reference_font_num():
    """python-docx writes <w:rFonts w:ascii="..."> per run.

    Numeric cells (data rows) must reference ``theme.font_num``
    (the active theme's monospace face); Chinese header / narrative
    text references ``theme.font_cn`` via the eastAsia attribute on
    the paragraph styles. Post the deterministic rendering refactor
    the DOCX builder reads the theme object passed to the renderer,
    not the module-level constants — so contract assertions here use
    the theme attributes to stay in lock-step with the renderer.
    """
    theme = CORPORATE_BLUE
    docx = render_outline(
        _outline_with_kpi_and_table(), DocxBlockRenderer(theme=theme),
    )
    with zipfile.ZipFile(io.BytesIO(docx)) as zf:
        xml = zf.read("word/document.xml").decode()

    assert theme.font_num in xml, (
        f"theme.font_num={theme.font_num!r} never appears in DOCX — "
        "numeric cells likely lost their monospace font."
    )
    assert theme.font_cn in xml, (
        f"theme.font_cn={theme.font_cn!r} never appears in DOCX — "
        "Chinese text fields lost their CJK font."
    )


def test_docx_growth_indicator_uses_font_num():
    """Growth indicators (yoy / mom) are numeric — must use T.FONT_NUM.

    Construct a minimal outline with a GrowthIndicatorsBlock to isolate
    this assertion from the table case above.
    """
    from backend.tools.report._outline import GrowthIndicatorsBlock

    o = ReportOutline(
        metadata={"title": "x", "author": "", "date": ""},
        sections=[
            OutlineSection(name="增长", role="status", blocks=[
                SectionCoverBlock(block_id="C1", index=1, title="增长"),
                GrowthIndicatorsBlock(
                    block_id="B1",
                    growth_rates={"throughput": {"yoy": 0.12, "mom": 0.03}},
                ),
            ]),
            OutlineSection(name="总结", role="appendix", blocks=[]),
        ],
    )
    theme = CORPORATE_BLUE
    docx = render_outline(o, DocxBlockRenderer(theme=theme))
    with zipfile.ZipFile(io.BytesIO(docx)) as zf:
        xml = zf.read("word/document.xml").decode()
    assert theme.font_num in xml


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def test_html_template_declares_separate_cn_and_num_fonts():
    """The static HTML template declares both CJK (serif) and monospace
    fonts via CSS custom properties. Verify the default theme font names
    are present in the output."""
    html = render_outline(_outline_with_kpi_and_table(), HtmlBlockRenderer())
    # The static template uses LIANGANG_JOURNAL fonts (the default theme).
    assert LIANGANG_JOURNAL.font_cn in html
    assert LIANGANG_JOURNAL.font_num in html


def test_html_kpi_value_uses_num_font():
    """CSS rule for .kpi-card .value sets font-family to var(--font-mono),
    which resolves to the theme monospace stack."""
    html = render_outline(_outline_with_kpi_and_table(), HtmlBlockRenderer())
    # The new static template uses CSS custom properties:
    #   .kpi-card .value { font-family: var(--font-mono); ... }
    # Verify the --font-mono declaration is present.
    assert "--font-mono" in html
    # Also verify the monospace font name is in the --font-mono value.
    assert f'"{LIANGANG_JOURNAL.font_num}"' in html


def test_html_table_stats_td_uses_num_font():
    """The agate table body cells use var(--font-mono) for numeric
    alignment, declared in the CSS template."""
    html = render_outline(_outline_with_kpi_and_table(), HtmlBlockRenderer())
    # The table.agate tbody td CSS rule uses var(--font-mono).
    assert "font-family: var(--font-mono)" in html


# ---------------------------------------------------------------------------
# Theme — sanity that font_cn != font_num so the audit isn't trivial
# ---------------------------------------------------------------------------

def test_corporate_blue_font_cn_and_num_are_distinct():
    assert CORPORATE_BLUE.font_cn != CORPORATE_BLUE.font_num, (
        "If font_cn and font_num collapse to the same family, the "
        "audit tests above degrade to a single-font check — the visual "
        "contract for numeric / CJK separation is lost."
    )

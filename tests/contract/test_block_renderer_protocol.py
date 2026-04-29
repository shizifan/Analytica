"""Step 2 — BlockRenderer protocol + dispatch tests.

Covers:
- ``render_outline`` invokes lifecycle hooks in the correct order
- Every block kind reaches its matching ``emit_*``
- ``TableBlock`` / ``ChartBlock`` / ``ChartTablePairBlock`` receive the
  resolved Asset objects (not just asset_ids)
- Unknown block kind raises ``ValueError``
- Skeleton base raises ``NotImplementedError`` until Step 3-6 override
- ``BlockRenderer`` protocol passes ``isinstance`` for skeleton renderers
- Concrete skeleton renderers (Markdown/DOCX/PPTX/HTML) construct cleanly
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.tools.report._block_renderer import (
    BlockRenderer,
    BlockRendererBase,
    _dispatch,
    render_outline,
)
from backend.tools.report._kpi_extractor import KPIItem
from backend.tools.report._outline import (
    ChartAsset,
    ChartBlock,
    ChartTablePairBlock,
    ComparisonGridBlock,
    GridColumn,
    GrowthIndicatorsBlock,
    KpiRowBlock,
    OutlineSection,
    ParagraphBlock,
    ReportOutline,
    SectionCoverBlock,
    StatsAsset,
    TableAsset,
    TableBlock,
    reset_id_counters,
)
from backend.tools.report._renderers import (
    DocxBlockRenderer,
    HtmlBlockRenderer,
    MarkdownBlockRenderer,
    PptxBlockRenderer,
)

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def _reset_ids():
    reset_id_counters()
    yield


# ---------------------------------------------------------------------------
# Recording renderer — captures every call for assertion
# ---------------------------------------------------------------------------

@dataclass
class _Call:
    method: str
    args: tuple[Any, ...] = field(default_factory=tuple)


class _RecordingRenderer:
    """Duck-types ``BlockRenderer``; logs each call instead of producing output."""

    def __init__(self) -> None:
        self.calls: list[_Call] = []

    def begin_document(self, outline):
        self.calls.append(_Call("begin_document", (outline,)))

    def end_document(self):
        self.calls.append(_Call("end_document"))
        return "<<DONE>>"

    def begin_section(self, section, index):
        self.calls.append(_Call("begin_section", (section.name, index)))

    def end_section(self, section, index):
        self.calls.append(_Call("end_section", (section.name, index)))

    def emit_kpi_row(self, block):
        self.calls.append(_Call("emit_kpi_row", (block.block_id,)))

    def emit_paragraph(self, block):
        self.calls.append(_Call("emit_paragraph", (block.block_id, block.style)))

    def emit_table(self, block, asset):
        self.calls.append(_Call("emit_table", (block.block_id, asset.asset_id)))

    def emit_chart(self, block, asset):
        self.calls.append(_Call("emit_chart", (block.block_id, asset.asset_id)))

    def emit_chart_table_pair(self, block, chart_asset, table_asset):
        self.calls.append(_Call(
            "emit_chart_table_pair",
            (block.block_id, chart_asset.asset_id, table_asset.asset_id),
        ))

    def emit_comparison_grid(self, block):
        self.calls.append(_Call("emit_comparison_grid", (block.block_id,)))

    def emit_growth_indicators(self, block):
        self.calls.append(_Call("emit_growth_indicators", (block.block_id,)))

    def emit_section_cover(self, block):
        self.calls.append(_Call("emit_section_cover", (block.block_id,)))


# ---------------------------------------------------------------------------
# Fixture: outline covering every block + asset kind
# ---------------------------------------------------------------------------

def _full_outline() -> ReportOutline:
    chart = ChartAsset(asset_id="C0001", source_task="T1", option={"series": []})
    table = TableAsset(asset_id="T0001", source_task="T2", df_records=[])
    stats = StatsAsset(asset_id="S0001", source_task="T3", summary_stats={})

    return ReportOutline(
        sections=[
            OutlineSection(
                name="一、摘要", role="summary",
                blocks=[
                    SectionCoverBlock(block_id="B1", index=0, title="一、摘要"),
                    KpiRowBlock(block_id="B2", items=[KPIItem(label="x", value="1")]),
                    ParagraphBlock(block_id="B3", text="lead", style="lead"),
                ],
            ),
            OutlineSection(
                name="二、现状", role="status",
                blocks=[
                    ChartBlock(block_id="B4", asset_id="C0001"),
                    TableBlock(block_id="B5", asset_id="T0001"),
                    ChartTablePairBlock(
                        block_id="B6",
                        chart_asset_id="C0001", table_asset_id="T0001",
                    ),
                    GrowthIndicatorsBlock(
                        block_id="B7",
                        growth_rates={"qty": {"yoy": 0.1}},
                    ),
                ],
            ),
            OutlineSection(
                name="三、建议", role="recommendation",
                blocks=[
                    ComparisonGridBlock(
                        block_id="B8",
                        columns=[GridColumn(title="短期", items=["a"])],
                    ),
                    ParagraphBlock(block_id="B9", text="warn", style="callout-warn"),
                ],
            ),
        ],
        assets={"C0001": chart, "T0001": table, "S0001": stats},
    )


# ---------------------------------------------------------------------------
# Lifecycle ordering
# ---------------------------------------------------------------------------

def test_render_outline_returns_end_document_payload():
    rec = _RecordingRenderer()
    out = render_outline(_full_outline(), rec)
    assert out == "<<DONE>>"


def test_render_outline_invokes_begin_and_end_exactly_once():
    rec = _RecordingRenderer()
    render_outline(_full_outline(), rec)
    methods = [c.method for c in rec.calls]
    assert methods.count("begin_document") == 1
    assert methods.count("end_document") == 1
    assert methods[0] == "begin_document"
    assert methods[-1] == "end_document"


def test_render_outline_brackets_each_section():
    rec = _RecordingRenderer()
    render_outline(_full_outline(), rec)
    methods = [c.method for c in rec.calls]
    assert methods.count("begin_section") == 3
    assert methods.count("end_section") == 3
    # Each begin must precede the matching end
    for section_idx in range(3):
        begin_pos = next(
            i for i, c in enumerate(rec.calls)
            if c.method == "begin_section" and c.args[1] == section_idx
        )
        end_pos = next(
            i for i, c in enumerate(rec.calls)
            if c.method == "end_section" and c.args[1] == section_idx
        )
        assert begin_pos < end_pos


def test_emit_calls_appear_inside_their_section_brackets():
    rec = _RecordingRenderer()
    render_outline(_full_outline(), rec)
    # Section 1 (status, idx=1) brackets 4 emits: chart, table, pair, growth
    begin = next(i for i, c in enumerate(rec.calls)
                 if c.method == "begin_section" and c.args[1] == 1)
    end = next(i for i, c in enumerate(rec.calls)
               if c.method == "end_section" and c.args[1] == 1)
    inner = [c.method for c in rec.calls[begin + 1: end]]
    assert inner == [
        "emit_chart", "emit_table",
        "emit_chart_table_pair", "emit_growth_indicators",
    ]


# ---------------------------------------------------------------------------
# Dispatch coverage — every block kind reaches its emit_*
# ---------------------------------------------------------------------------

def test_every_block_kind_dispatches_to_matching_emit():
    rec = _RecordingRenderer()
    render_outline(_full_outline(), rec)
    methods = {c.method for c in rec.calls}
    expected_emits = {
        "emit_section_cover",
        "emit_kpi_row",
        "emit_paragraph",
        "emit_chart",
        "emit_table",
        "emit_chart_table_pair",
        "emit_growth_indicators",
        "emit_comparison_grid",
    }
    missing = expected_emits - methods
    assert not missing, f"Block kinds without dispatch: {missing}"


def test_paragraph_style_is_passed_through():
    rec = _RecordingRenderer()
    render_outline(_full_outline(), rec)
    paragraph_calls = [c for c in rec.calls if c.method == "emit_paragraph"]
    styles = [c.args[1] for c in paragraph_calls]
    assert "lead" in styles
    assert "callout-warn" in styles


# ---------------------------------------------------------------------------
# Asset resolution — emits receive the resolved Asset, not just asset_id
# ---------------------------------------------------------------------------

def test_emit_table_receives_resolved_asset():
    outline = _full_outline()
    rec = _RecordingRenderer()
    render_outline(outline, rec)
    table_call = next(c for c in rec.calls if c.method == "emit_table")
    assert table_call.args == ("B5", "T0001")


def test_emit_chart_receives_resolved_asset():
    outline = _full_outline()
    rec = _RecordingRenderer()
    render_outline(outline, rec)
    chart_call = next(c for c in rec.calls if c.method == "emit_chart")
    assert chart_call.args == ("B4", "C0001")


def test_emit_chart_table_pair_receives_both_assets():
    outline = _full_outline()
    rec = _RecordingRenderer()
    render_outline(outline, rec)
    pair_call = next(c for c in rec.calls if c.method == "emit_chart_table_pair")
    assert pair_call.args == ("B6", "C0001", "T0001")


def test_dangling_asset_id_raises_keyerror():
    outline = ReportOutline(sections=[
        OutlineSection(name="x", blocks=[
            ChartBlock(block_id="B1", asset_id="C9999"),
        ]),
    ])  # no assets registered
    with pytest.raises(KeyError, match="C9999"):
        render_outline(outline, _RecordingRenderer())


# ---------------------------------------------------------------------------
# Unknown block kind
# ---------------------------------------------------------------------------

class _PhantomBlock:
    block_id = "B9999"
    kind = "phantom"


def test_unknown_block_kind_raises_valueerror():
    rec = _RecordingRenderer()
    outline = ReportOutline()
    with pytest.raises(ValueError, match="Unknown block kind"):
        _dispatch(_PhantomBlock(), outline, rec)


# ---------------------------------------------------------------------------
# Skeleton base — methods raise until concrete renderers override
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("renderer_cls", [
    MarkdownBlockRenderer,
    DocxBlockRenderer,
    PptxBlockRenderer,
    HtmlBlockRenderer,
])
def test_skeleton_renderer_constructs_cleanly(renderer_cls):
    r = renderer_cls()
    assert isinstance(r, BlockRendererBase)


def test_base_class_raises_when_no_renderer_overrides():
    """When a renderer subclass forgets to override a method, the base
    class implementation must raise — the safety net for Sprint 3+ when
    new block kinds are added and renderers fall behind."""
    from backend.tools.report._block_renderer import BlockRendererBase

    class _Forgetful(BlockRendererBase):
        _step_label = "TestSubclass"

    r = _Forgetful()
    with pytest.raises(NotImplementedError, match="TestSubclass"):
        r.emit_kpi_row(KpiRowBlock(block_id="B1"))


def test_all_concrete_renderers_implemented():
    """All four backends now ship Step 3-6 implementations; no skeleton
    label should be visible."""
    for cls in (
        MarkdownBlockRenderer, DocxBlockRenderer,
        PptxBlockRenderer, HtmlBlockRenderer,
    ):
        # Sanity: a method that the base would raise on, the subclass
        # must have replaced. Exercising end_document is the cheapest
        # method that doesn't need fixture data.
        r = cls()
        try:
            r.end_document()
        except NotImplementedError:
            pytest.fail(f"{cls.__name__}.end_document still falls through to base")
        except Exception:
            pass  # Other errors (e.g. python-docx state) are fine — not a skeleton


# ---------------------------------------------------------------------------
# Protocol structural typing
# ---------------------------------------------------------------------------

def test_recording_renderer_satisfies_protocol():
    assert isinstance(_RecordingRenderer(), BlockRenderer)


def test_skeleton_renderers_satisfy_protocol():
    for cls in (MarkdownBlockRenderer, DocxBlockRenderer,
                PptxBlockRenderer, HtmlBlockRenderer):
        assert isinstance(cls(), BlockRenderer), f"{cls.__name__} fails protocol check"


def test_partial_object_does_not_satisfy_protocol():
    class _Partial:
        def begin_document(self, outline): ...
        # missing all other methods
    assert not isinstance(_Partial(), BlockRenderer)

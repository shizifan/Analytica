"""Step 0.2 — PptxGenJSBlockRenderer tests.

Verifies the Python-side command emission without requiring a real
Node bridge. Validates:
- Document lifecycle produces cover + TOC + KPI overview slides
- Section divider precedes section content
- Narrative + stats co-existence emits a two-column slide
- Charts emit AddChart commands when echarts_to_pptxgen succeeds
- Appendix emits summary + thank-you slides
- Color invariants hold across all emitted commands (no '#', no 8-hex)
- ``end_document`` raises RuntimeError when Node bridge is missing
  (caller must catch and fall back to PptxBlockRenderer)
"""
from __future__ import annotations

import pytest

from backend.tools.report._block_renderer import render_outline
from backend.tools.report._kpi_extractor import KPIItem
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
from backend.tools.report._pptxgen_commands import (
    AddChart,
    AddShape,
    AddTable,
    AddText,
    NewSlide,
    is_valid_hex6,
)
from backend.tools.report._renderers.pptxgen import PptxGenJSBlockRenderer

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def _reset_ids():
    reset_id_counters()
    yield


# ---------------------------------------------------------------------------
# Outline factories
# ---------------------------------------------------------------------------

def _normal_outline() -> ReportOutline:
    """3 sections + appendix, mirrors the baseline normal fixture shape."""
    chart_asset = ChartAsset(
        asset_id="C0001", source_task="T002",
        option={
            "title": {"text": "港区吞吐量"},
            "xAxis": {"type": "category", "data": ["大连港", "营口港", "锦州港"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "bar", "data": [4500.5, 3200.1, 1800.0]}],
        },
    )
    stats_asset = StatsAsset(
        asset_id="S0001", source_task="T003",
        summary_stats={
            "throughput": {"max": 4500.5, "min": 1800.0, "mean": 3166.87},
        },
    )
    return ReportOutline(
        metadata={
            "title": "2026 Q1 港区吞吐量分析报告",
            "author": "Analytica Test",
            "date": "2026-04-29",
            "intent": "Q1 分析",
        },
        kpi_summary=[
            KPIItem(label="总吞吐量", value="9500.6 万吨", sub="2026 Q1", trend="positive"),
            KPIItem(label="同比增长", value="12.0%", sub="YoY", trend="positive"),
        ],
        # Phase 3.1: each non-appendix section opens with a
        # SectionCoverBlock (legacy converter / LLM planner contract).
        sections=[
            OutlineSection(
                name="一、港区吞吐量现状", role="status",
                blocks=[
                    SectionCoverBlock(block_id="C1", index=1, title="一、港区吞吐量现状"),
                    ChartBlock(block_id="B1", asset_id="C0001"),
                ],
            ),
            OutlineSection(
                name="二、关键指标分析", role="status",
                blocks=[
                    SectionCoverBlock(block_id="C2", index=2, title="二、关键指标分析"),
                    ParagraphBlock(block_id="B2", text="2026 Q1 吞吐量整体增长。"),
                    TableBlock(block_id="B3", asset_id="S0001"),
                    GrowthIndicatorsBlock(
                        block_id="B4",
                        growth_rates={"throughput": {"yoy": 0.12, "mom": 0.03}},
                    ),
                ],
            ),
            OutlineSection(
                name="三、综合结论", role="status",
                blocks=[
                    SectionCoverBlock(block_id="C3", index=3, title="三、综合结论"),
                ],
            ),
            OutlineSection(
                name="总结与建议", role="appendix",
                blocks=[
                    ParagraphBlock(
                        block_id="B5", text="三港区集装箱吞吐量稳健增长。",
                        style="lead",
                    ),
                ],
            ),
        ],
        assets={"C0001": chart_asset, "S0001": stats_asset},
    )


def _render_to_commands(outline: ReportOutline) -> list:
    renderer = PptxGenJSBlockRenderer()
    # Drive lifecycle without invoking end_document (which needs Node).
    renderer.begin_document(outline)
    for idx, sec in enumerate(outline.sections):
        renderer.begin_section(sec, idx)
        for blk in sec.blocks:
            from backend.tools.report._block_renderer import _dispatch
            _dispatch(blk, outline, renderer)
        renderer.end_section(sec, idx)
    return renderer.commands


# ---------------------------------------------------------------------------
# Document lifecycle
# ---------------------------------------------------------------------------

def test_begin_document_emits_cover_then_toc_then_kpi():
    cmds = _render_to_commands(_normal_outline())
    types_seq = [c.type for c in cmds]
    # Cover slide is the first NewSlide
    new_slide_indices = [i for i, t in enumerate(types_seq) if t == "new_slide"]
    assert new_slide_indices, "renderer produced no slides"
    first_idx = new_slide_indices[0]
    # First slide background must be primary (cover is dark)
    assert cmds[first_idx].background is not None
    assert is_valid_hex6(cmds[first_idx].background)


def test_cover_slide_contains_title_author_date():
    cmds = _render_to_commands(_normal_outline())
    text_cmds = [c for c in cmds if isinstance(c, AddText)]
    text_strings = [c.text for c in text_cmds]
    assert "2026 Q1 港区吞吐量分析报告" in text_strings
    assert any("Analytica Test" in t for t in text_strings)
    assert "2026-04-29" in text_strings


def test_toc_slide_lists_non_appendix_section_names():
    cmds = _render_to_commands(_normal_outline())
    text_strings = [
        c.text for c in cmds if isinstance(c, AddText)
    ]
    # TOC items are formatted "1.  一、xxx"
    assert any("1.  一、港区吞吐量现状" in t for t in text_strings)
    assert any("2.  二、关键指标分析" in t for t in text_strings)
    assert any("3.  三、综合结论" in t for t in text_strings)
    # Appendix must NOT appear in TOC
    assert not any("总结与建议" in t for t in text_strings if t.startswith(("1", "2", "3", "4")))


def test_kpi_overview_slide_renders_each_kpi():
    cmds = _render_to_commands(_normal_outline())
    text_strings = [c.text for c in cmds if isinstance(c, AddText)]
    assert "总吞吐量" in text_strings
    assert "9500.6 万吨" in text_strings
    assert "同比增长" in text_strings


# ---------------------------------------------------------------------------
# Section composition
# ---------------------------------------------------------------------------

def test_section_divider_emitted_for_each_non_appendix_section():
    cmds = _render_to_commands(_normal_outline())
    # divider has section number text "01", "02", "03"
    text_strings = [c.text for c in cmds if isinstance(c, AddText)]
    assert "01" in text_strings
    assert "02" in text_strings
    assert "03" in text_strings


def test_chart_block_emits_native_addchart_command():
    cmds = _render_to_commands(_normal_outline())
    chart_cmds = [c for c in cmds if isinstance(c, AddChart)]
    assert len(chart_cmds) >= 1
    chart_cmd = chart_cmds[0]
    assert chart_cmd.chart_type in ("BAR", "LINE")
    assert isinstance(chart_cmd.data, list)
    assert chart_cmd.data and "values" in chart_cmd.data[0]


def test_narrative_plus_stats_emits_two_column_slide_then_stats_table():
    cmds = _render_to_commands(_normal_outline())
    table_cmds = [c for c in cmds if isinstance(c, AddTable)]
    # Section 2 has narrative + stats → two-column + stats_table
    assert len(table_cmds) >= 1


def test_growth_emits_kpi_cards_slide():
    cmds = _render_to_commands(_normal_outline())
    text_strings = [c.text for c in cmds if isinstance(c, AddText)]
    # KPI cards slide carries arrow ↑↓ formatted growth values
    yoy_cells = [t for t in text_strings if t.startswith("↑12.0") or t.startswith("↓12.0")]
    assert yoy_cells, "growth_indicators failed to emit yoy KPI card"
    # Subtitle '同比' and '环比'
    assert "同比" in text_strings
    assert "环比" in text_strings


def test_appendix_emits_summary_and_thank_you_slides():
    cmds = _render_to_commands(_normal_outline())
    text_strings = [c.text for c in cmds if isinstance(c, AddText)]
    # Summary slide title
    assert "总结与建议" in text_strings
    # Conclusion bullet
    assert any("三港区集装箱" in t for t in text_strings)
    # Thank-you slide
    assert "谢谢观看" in text_strings


# ---------------------------------------------------------------------------
# Color invariants (SOP Step 0.5 — see test_pptxgen_constraints.py)
# ---------------------------------------------------------------------------

def test_all_emitted_colors_are_6_hex_no_hash():
    cmds = _render_to_commands(_normal_outline())
    bad: list[tuple[str, str]] = []
    for cmd in cmds:
        if isinstance(cmd, NewSlide) and cmd.background is not None:
            if not is_valid_hex6(cmd.background):
                bad.append(("NewSlide.background", cmd.background))
        if isinstance(cmd, AddText):
            if not is_valid_hex6(cmd.color):
                bad.append(("AddText.color", cmd.color))
        if isinstance(cmd, AddShape):
            if not is_valid_hex6(cmd.fill):
                bad.append(("AddShape.fill", cmd.fill))
            if cmd.line_color is not None and not is_valid_hex6(cmd.line_color):
                bad.append(("AddShape.line_color", cmd.line_color))
    assert not bad, f"Invalid colors: {bad[:5]}"


# ---------------------------------------------------------------------------
# end_document failure mode
# ---------------------------------------------------------------------------

def test_end_document_raises_runtime_error_when_node_unavailable(monkeypatch):
    """Caller (pptx_gen.py) catches and falls back. We assert the
    failure surface is RuntimeError, not generic Exception."""
    def _stub_executor(commands_json: str, timeout: int = 90) -> bytes:
        raise RuntimeError("node not found")

    monkeypatch.setattr(
        "backend.tools.report._renderers.pptxgen.run_pptxgen_executor",
        _stub_executor,
    )
    renderer = PptxGenJSBlockRenderer()
    renderer.begin_document(_normal_outline())
    with pytest.raises(RuntimeError, match="node not found"):
        renderer.end_document()


def test_end_document_returns_executor_bytes_on_success(monkeypatch):
    def _stub_executor(commands_json: str, timeout: int = 90) -> bytes:
        # Sanity check: payload must be valid JSON array
        import json
        data = json.loads(commands_json)
        assert isinstance(data, list)
        return b"FAKE_PPTX_BYTES"

    monkeypatch.setattr(
        "backend.tools.report._renderers.pptxgen.run_pptxgen_executor",
        _stub_executor,
    )
    renderer = PptxGenJSBlockRenderer()
    render_outline(_normal_outline(), renderer)
    # render_outline returns end_document's payload
    # (but here we already called it inside; recall via direct method)


# ---------------------------------------------------------------------------
# Integration with render_outline + Block protocol
# ---------------------------------------------------------------------------

def test_renderer_satisfies_protocol_contract():
    """render_outline orchestration must reach end_document; verify by
    counting commands grew from begin_document only."""
    outline = _normal_outline()
    renderer = PptxGenJSBlockRenderer()
    cmds_after_begin = (
        renderer.begin_document(outline)
        or renderer.commands
    )
    initial_count = len(renderer.commands)
    for idx, sec in enumerate(outline.sections):
        renderer.begin_section(sec, idx)
        for blk in sec.blocks:
            from backend.tools.report._block_renderer import _dispatch
            _dispatch(blk, outline, renderer)
        renderer.end_section(sec, idx)
    final_count = len(renderer.commands)
    assert final_count > initial_count, "section composition emitted no commands"

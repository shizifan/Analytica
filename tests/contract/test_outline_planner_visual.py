"""Phase 6 / 6.4 — LLM planner visual acceptance.

Verifies that an LLM response containing visual blocks (callout,
comparison_grid, chart_table_pair, kpi_row, growth_indicators) flows
end-to-end through ``plan_outline`` and renders correctly in all four
backends.

Companion to ``test_outline_planner_llm.py`` (which checks outline
**construction**) and ``test_enhanced_baseline.py`` (which checks
**rendering** of a hand-built outline). This module locks down the
seam between them — ensuring the LLM planner's parsed outline drives
the same visual contracts.

Note: ``section_cover`` and ``TableBlock.highlight_rules`` are NOT
exercised here because the LLM planner explicitly rejects /
strips them today (see ``_planner_prompts.py``). Adding LLM-driven
covers / highlights would require planner-side support first;
``test_planner_drops_unsupported_visual_blocks`` documents this gap.
"""
from __future__ import annotations

import json

import pytest

from backend.tools.report._block_renderer import render_outline
from backend.tools.report._outline import (
    ChartTablePairBlock,
    ComparisonGridBlock,
    GrowthIndicatorsBlock,
    KpiRowBlock,
    ParagraphBlock,
)
from backend.tools.report._outline_planner import plan_outline
from backend.tools.report._renderers import (
    DocxBlockRenderer,
    HtmlBlockRenderer,
    MarkdownBlockRenderer,
    PptxBlockRenderer,
)

from tests.contract._report_baseline import (
    freeze_kpis,
    make_normal_fixture,
    override_settings,
)

pytestmark = pytest.mark.contract


# ---------------------------------------------------------------------------
# Test environment
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _planner_env(monkeypatch):
    freeze_kpis(monkeypatch)
    override_settings(
        monkeypatch,
        REPORT_AGENT_ENABLED=False,
        REPORT_OUTLINE_PLANNER_ENABLED=True,
    )
    monkeypatch.setattr(
        "backend.tools.report._pptxgen_builder.check_pptxgen_available",
        lambda: False,
    )


def _stub_invoke_llm(monkeypatch, payload: dict) -> None:
    text = json.dumps(payload, ensure_ascii=False)

    async def _stub(*args, **kwargs):  # noqa: ARG001
        return {"text": text}

    monkeypatch.setattr(
        "backend.tools.report._outline_planner.invoke_llm", _stub,
    )


def _visual_response() -> dict:
    """LLM response that uses every visual block kind the planner
    currently honours, mapped onto the ``normal`` fixture's 3 sections.

    Maps to assets the legacy converter creates:
      - C0001 / T0001 → from T001 throughput task
      - S0001         → from T003 stats payload
    """
    return {
        "kpi_summary": [
            {"label": "总吞吐量", "value": "9500.6 万吨",
             "sub": "2026 Q1", "trend": "positive"},
            {"label": "同比增长", "value": "12.0%",
             "sub": "YoY", "trend": "positive"},
        ],
        "sections": [
            {
                "name": "一、港区吞吐量现状",
                "role": "status",
                "source_tasks": ["T001", "T002"],
                "blocks": [
                    {"kind": "kpi_row", "items": [
                        {"label": "顶级港", "value": "大连港",
                         "sub": "4500.5 万吨", "trend": "positive"},
                    ]},
                    {"kind": "chart_table_pair",
                     "chart_asset_id": "C0001",
                     "table_asset_id": "T0001",
                     "layout": "h"},
                    {"kind": "paragraph",
                     "text": "锦州港 yoy -3% 已连续两个季度走弱，需要警惕。",
                     "style": "callout-warn"},
                ],
            },
            {
                "name": "二、关键指标分析",
                "role": "status",
                "source_tasks": ["T003"],
                "blocks": [
                    {"kind": "table", "asset_id": "S0001",
                     "caption": "统计数据概览"},
                    {"kind": "growth_indicators",
                     "growth_rates": {
                         "throughput": {"yoy": 0.12, "mom": 0.03},
                     }},
                    {"kind": "paragraph",
                     "text": "装卸效率提升对总吞吐贡献 31%，建议复制。",
                     "style": "callout-info"},
                ],
            },
            {
                "name": "三、综合结论",
                "role": "recommendation",
                "source_tasks": ["T004"],
                "blocks": [
                    {"kind": "comparison_grid",
                     "columns": [
                         {"title": "短期 (Q2)",  "items": ["设备巡检", "装卸 SOP 复用"]},
                         {"title": "中期 (H2)",  "items": ["运力 +15%"]},
                         {"title": "长期",       "items": ["一体化调度"]},
                     ]},
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Outline construction — visual blocks survive parsing
# ---------------------------------------------------------------------------

async def test_visual_blocks_present_in_planned_outline(monkeypatch):
    _stub_invoke_llm(monkeypatch, _visual_response())
    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(
        params, ctx,
        task_order=params["_task_order"],
        intent=params.get("intent", ""),
    )

    assert outline.planner_mode == "llm"

    sec0_kinds = [b.kind for b in outline.sections[0].blocks]
    assert "kpi_row" in sec0_kinds
    assert "chart_table_pair" in sec0_kinds
    callout_blocks = [
        b for sec in outline.sections for b in sec.blocks
        if isinstance(b, ParagraphBlock) and b.style.startswith("callout-")
    ]
    assert len(callout_blocks) == 2
    styles = {b.style for b in callout_blocks}
    assert styles == {"callout-warn", "callout-info"}

    # comparison_grid intact in section 2
    grid = outline.sections[2].blocks[0]
    assert isinstance(grid, ComparisonGridBlock)
    assert [c.title for c in grid.columns] == [
        "短期 (Q2)", "中期 (H2)", "长期",
    ]


async def test_chart_table_pair_resolves_assets(monkeypatch):
    _stub_invoke_llm(monkeypatch, _visual_response())
    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    pair = next(
        b for sec in outline.sections for b in sec.blocks
        if isinstance(b, ChartTablePairBlock)
    )
    # Both referenced assets exist in outline.assets
    assert pair.chart_asset_id in outline.assets
    assert pair.table_asset_id in outline.assets


async def test_growth_indicators_round_trip(monkeypatch):
    _stub_invoke_llm(monkeypatch, _visual_response())
    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])
    growth = next(
        b for sec in outline.sections for b in sec.blocks
        if isinstance(b, GrowthIndicatorsBlock)
    )
    assert growth.growth_rates["throughput"]["yoy"] == 0.12


async def test_kpi_row_block_in_first_section(monkeypatch):
    _stub_invoke_llm(monkeypatch, _visual_response())
    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])
    kpi_blk = next(
        b for b in outline.sections[0].blocks if isinstance(b, KpiRowBlock)
    )
    assert [k.label for k in kpi_blk.items] == ["顶级港"]


# ---------------------------------------------------------------------------
# 4-end rendering — visual markers reach output
# ---------------------------------------------------------------------------

async def _planned_outline(monkeypatch):
    _stub_invoke_llm(monkeypatch, _visual_response())
    params, ctx, _ = make_normal_fixture()
    return await plan_outline(
        params, ctx,
        task_order=params["_task_order"],
        intent=params.get("intent", ""),
    )


async def test_markdown_renders_callouts_and_grid(monkeypatch):
    outline = await _planned_outline(monkeypatch)
    md = render_outline(outline, MarkdownBlockRenderer())

    assert "> ⚠️ **注意**：锦州港 yoy -3%" in md
    assert "> 💡 装卸效率提升对总吞吐贡献 31%" in md
    # Three grid columns rendered as bold headings + bullets
    assert "**短期 (Q2)**" in md
    assert "**中期 (H2)**" in md
    assert "**长期**" in md


async def test_html_renders_callout_classes_and_grid(monkeypatch):
    outline = await _planned_outline(monkeypatch)
    html = render_outline(outline, HtmlBlockRenderer())

    assert '<div class="callout warn">锦州港 yoy -3%' in html
    assert '<div class="callout info">装卸效率' in html
    # Comparison grid column titles surface in HTML
    assert "短期 (Q2)" in html
    assert "中期 (H2)" in html


async def test_docx_renders_visual_blocks(monkeypatch):
    """DOCX is binary — verify it builds without error and the
    structural skeleton contains the callout & grid text. Text
    extraction is via the existing baseline normaliser."""
    from tests.contract._report_baseline import docx_to_text_tree

    outline = await _planned_outline(monkeypatch)
    blob = render_outline(outline, DocxBlockRenderer())
    assert isinstance(blob, (bytes, bytearray))
    tree = docx_to_text_tree(blob)
    assert "锦州港 yoy -3%" in tree
    assert "装卸效率提升" in tree
    assert "短期 (Q2)" in tree
    assert "中期 (H2)" in tree


async def test_pptx_renders_visual_blocks(monkeypatch):
    from tests.contract._report_baseline import pptx_to_text_tree

    outline = await _planned_outline(monkeypatch)
    blob = render_outline(outline, PptxBlockRenderer())
    assert isinstance(blob, (bytes, bytearray))
    tree = pptx_to_text_tree(blob)
    # Callout text appears somewhere in slide bodies
    assert "锦州港" in tree
    assert "装卸效率" in tree
    assert "短期 (Q2)" in tree


# ---------------------------------------------------------------------------
# Documented gap — LLM cannot drive section_cover or highlight_rules today
# ---------------------------------------------------------------------------

async def test_planner_rejects_section_cover_and_falls_back(monkeypatch):
    """LLM-emitted ``section_cover`` blocks are rejected by the
    validator → planner falls back to rule mode (which inserts
    section_cover blocks automatically). This test pins the contract
    so we notice if/when planner support is added.

    Symptoms when this contract changes:
      - planner_mode flips to ``llm`` instead of ``rule_fallback``
      - degradations list no longer mentions ``section_cover``
    """
    response = _visual_response()
    response["sections"][0]["blocks"].insert(
        0,
        {"kind": "section_cover", "index": 1,
         "title": "LLM 不应能驱动封面", "subtitle": "今后若放开则更新本测试"},
    )
    _stub_invoke_llm(monkeypatch, response)
    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    assert outline.planner_mode == "rule_fallback", (
        "Planner should reject section_cover and fall back to rule mode"
    )
    assert any(
        "section_cover" in d.get("reason", "")
        for d in outline.degradations
    ), f"Expected 'section_cover' in degradations, got {outline.degradations}"


async def test_planner_silently_drops_table_highlight_rules(monkeypatch):
    """LLM-emitted ``highlight_rules`` on table blocks are silently
    dropped (the parser ignores unknown fields rather than rejecting
    the response). Pinning this so we know if/when LLM-driven
    highlights become a real feature."""
    response = _visual_response()
    for sec in response["sections"]:
        for blk in sec["blocks"]:
            if blk.get("kind") == "table":
                blk["highlight_rules"] = [{"col": "x", "color": "positive"}]

    _stub_invoke_llm(monkeypatch, response)
    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    # LLM mode still succeeds
    assert outline.planner_mode == "llm"
    # but every TableBlock comes back with empty highlight_rules
    table_blocks = [
        b for sec in outline.sections for b in sec.blocks
        if b.kind == "table"
    ]
    assert table_blocks, "expected at least one table block in fixture"
    for tb in table_blocks:
        assert tb.highlight_rules == []

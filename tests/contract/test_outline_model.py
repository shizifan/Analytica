"""Step 1 — ReportOutline data model tests.

Covers:
- ID minting (block + per-asset-kind counters, reset)
- All 8 block kinds construct cleanly with sane defaults
- to_json / from_json round-trip preserves every field
- ``find_block`` and ``get_asset`` accessors
- Schema version mismatch raises
- Unknown block / asset kind in JSON raises
"""
from __future__ import annotations

import pytest

from backend.tools.report._outline import KPIItem
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
    SCHEMA_VERSION,
    SectionCoverBlock,
    StatsAsset,
    TableAsset,
    TableBlock,
    new_asset_id,
    new_block_id,
    reset_id_counters,
)

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def _reset_ids():
    reset_id_counters()
    yield


# ---------------------------------------------------------------------------
# ID minting
# ---------------------------------------------------------------------------

def test_block_id_counter_increments_and_pads():
    assert new_block_id() == "B0001"
    assert new_block_id() == "B0002"
    assert new_block_id() == "B0003"


def test_asset_id_counters_are_independent_per_kind():
    assert new_asset_id("chart") == "C0001"
    assert new_asset_id("table") == "T0001"
    assert new_asset_id("chart") == "C0002"
    assert new_asset_id("stats") == "S0001"
    assert new_asset_id("table") == "T0002"


def test_unknown_asset_kind_raises():
    with pytest.raises(ValueError, match="Unknown asset kind"):
        new_asset_id("doughnut")


def test_reset_id_counters_restarts_all_sequences():
    new_block_id()
    new_asset_id("chart")
    new_asset_id("table")
    reset_id_counters()
    assert new_block_id() == "B0001"
    assert new_asset_id("chart") == "C0001"
    assert new_asset_id("table") == "T0001"
    assert new_asset_id("stats") == "S0001"


# ---------------------------------------------------------------------------
# Construction defaults
# ---------------------------------------------------------------------------

def test_default_outline_has_schema_version_and_empty_collections():
    o = ReportOutline()
    assert o.schema_version == SCHEMA_VERSION
    assert o.kpi_summary == []
    assert o.sections == []
    assert o.assets == {}
    assert o.degradations == []
    assert o.planner_mode == "llm"


def test_each_block_kind_constructs_with_correct_kind_field():
    cases = [
        (KpiRowBlock(block_id="B1"), "kpi_row"),
        (ParagraphBlock(block_id="B2", text="hi"), "paragraph"),
        (TableBlock(block_id="B3", asset_id="T0001"), "table"),
        (ChartBlock(block_id="B4", asset_id="C0001"), "chart"),
        (ChartTablePairBlock(
            block_id="B5", chart_asset_id="C0001", table_asset_id="T0001"
        ), "chart_table_pair"),
        (ComparisonGridBlock(block_id="B6"), "comparison_grid"),
        (GrowthIndicatorsBlock(block_id="B7"), "growth_indicators"),
        (SectionCoverBlock(block_id="B8", index=0, title="一、概览"), "section_cover"),
    ]
    for blk, expected_kind in cases:
        assert blk.kind == expected_kind, f"{type(blk).__name__} has wrong kind"


def test_each_asset_kind_constructs_with_correct_kind_field():
    chart = ChartAsset(asset_id="C0001", source_task="T001", option={"series": []})
    table = TableAsset(asset_id="T0001", source_task="T001", df_records=[])
    stats = StatsAsset(asset_id="S0001", source_task="T001", summary_stats={})
    assert chart.kind == "chart"
    assert table.kind == "table"
    assert stats.kind == "stats"


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------

def test_get_asset_returns_registered_asset():
    o = ReportOutline()
    asset = ChartAsset(asset_id="C0001", source_task="T1", option={})
    o.assets["C0001"] = asset
    assert o.get_asset("C0001") is asset


def test_get_asset_raises_on_missing():
    o = ReportOutline()
    with pytest.raises(KeyError, match="C9999"):
        o.get_asset("C9999")


def test_find_block_searches_all_sections():
    blk = ParagraphBlock(block_id="B0042", text="needle")
    o = ReportOutline(sections=[
        OutlineSection(name="S1", blocks=[ParagraphBlock(block_id="B1", text="a")]),
        OutlineSection(name="S2", blocks=[ParagraphBlock(block_id="B2", text="b"), blk]),
    ])
    found = o.find_block("B0042")
    assert found is blk
    assert o.find_block("B9999") is None


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

def _make_full_outline() -> ReportOutline:
    """Build an outline that exercises every block + asset kind."""
    chart_asset = ChartAsset(
        asset_id="C0001", source_task="T001",
        option={"series": [{"type": "bar", "data": [1, 2, 3]}]},
        endpoint="throughput_by_region",
    )
    table_asset = TableAsset(
        asset_id="T0001", source_task="T002",
        df_records=[{"port": "大连", "qty": 4500.5}],
        columns_meta=[{"name": "port", "label": "港区"}],
        endpoint="throughput_by_region",
    )
    stats_asset = StatsAsset(
        asset_id="S0001", source_task="T003",
        summary_stats={"throughput": {"max": 4500.5, "min": 1800.0}},
    )

    return ReportOutline(
        metadata={"title": "T", "author": "A", "date": "2026-04-29", "intent": "i"},
        kpi_summary=[
            KPIItem(label="总量", value="9500", sub="Q1", trend="positive"),
            KPIItem(label="增长", value="12%", sub="YoY", trend=None),
        ],
        sections=[
            OutlineSection(
                name="一、摘要", role="summary", source_tasks=["T001"],
                blocks=[
                    KpiRowBlock(
                        block_id="B0001",
                        items=[KPIItem(label="x", value="1")],
                    ),
                    ParagraphBlock(block_id="B0002", text="lead text", style="lead"),
                    SectionCoverBlock(
                        block_id="B0003", index=0, title="封面", subtitle="副标题",
                    ),
                ],
            ),
            OutlineSection(
                name="二、现状", role="status", source_tasks=["T001", "T002"],
                blocks=[
                    ChartBlock(block_id="B0004", asset_id="C0001", caption="图1"),
                    TableBlock(
                        block_id="B0005", asset_id="T0001", caption="表1",
                        highlight_rules=[{"col": "qty", "rule": "max"}],
                    ),
                    ChartTablePairBlock(
                        block_id="B0006",
                        chart_asset_id="C0001", table_asset_id="T0001",
                        layout="h",
                    ),
                    GrowthIndicatorsBlock(
                        block_id="B0007",
                        growth_rates={"qty": {"yoy": 0.12, "mom": None}},
                    ),
                    ParagraphBlock(
                        block_id="B0008",
                        text="风险提示", style="callout-warn",
                    ),
                ],
            ),
            OutlineSection(
                name="三、建议", role="recommendation", source_tasks=[],
                blocks=[
                    ComparisonGridBlock(
                        block_id="B0009",
                        columns=[
                            GridColumn(title="短期", items=["a", "b"]),
                            GridColumn(title="中期", items=["c"]),
                            GridColumn(title="长期", items=["d", "e"]),
                        ],
                    ),
                ],
            ),
        ],
        assets={
            "C0001": chart_asset,
            "T0001": table_asset,
            "S0001": stats_asset,
        },
        degradations=[{"kind": "missing_data", "task_id": "T999"}],
        planner_mode="llm",
    )


def test_roundtrip_preserves_every_field():
    original = _make_full_outline()
    rebuilt = ReportOutline.from_json(original.to_json())
    assert rebuilt.to_json() == original.to_json()


def test_roundtrip_preserves_planner_mode_and_degradations():
    original = _make_full_outline()
    rebuilt = ReportOutline.from_json(original.to_json())
    assert rebuilt.planner_mode == "llm"
    assert rebuilt.degradations == [{"kind": "missing_data", "task_id": "T999"}]


def test_roundtrip_preserves_block_kind_specific_fields():
    original = _make_full_outline()
    rebuilt = ReportOutline.from_json(original.to_json())

    # ChartTablePair → layout
    pair = next(b for b in rebuilt.sections[1].blocks
                if isinstance(b, ChartTablePairBlock))
    assert pair.layout == "h"

    # Paragraph → callout-warn style
    callout = rebuilt.sections[1].blocks[-1]
    assert isinstance(callout, ParagraphBlock)
    assert callout.style == "callout-warn"

    # Grid → 3 columns with items
    grid = rebuilt.sections[2].blocks[0]
    assert isinstance(grid, ComparisonGridBlock)
    assert [c.title for c in grid.columns] == ["短期", "中期", "长期"]
    assert grid.columns[0].items == ["a", "b"]


def test_roundtrip_preserves_asset_endpoint_and_payload():
    original = _make_full_outline()
    rebuilt = ReportOutline.from_json(original.to_json())
    chart = rebuilt.assets["C0001"]
    table = rebuilt.assets["T0001"]
    assert isinstance(chart, ChartAsset)
    assert chart.endpoint == "throughput_by_region"
    assert chart.option["series"][0]["data"] == [1, 2, 3]
    assert isinstance(table, TableAsset)
    assert table.df_records == [{"port": "大连", "qty": 4500.5}]


def test_roundtrip_preserves_kpi_items_with_none_trend():
    original = _make_full_outline()
    rebuilt = ReportOutline.from_json(original.to_json())
    assert [k.label for k in rebuilt.kpi_summary] == ["总量", "增长"]
    assert rebuilt.kpi_summary[0].trend == "positive"
    assert rebuilt.kpi_summary[1].trend is None


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_unknown_schema_version_raises():
    payload = ReportOutline().to_json()
    payload["schema_version"] = "9.9"
    with pytest.raises(ValueError, match="schema_version"):
        ReportOutline.from_json(payload)


def test_unknown_block_kind_in_json_raises():
    payload = ReportOutline(sections=[
        OutlineSection(name="x", blocks=[]),
    ]).to_json()
    payload["sections"][0]["blocks"].append({"kind": "doughnut", "block_id": "B1"})
    with pytest.raises(ValueError, match="Unknown block kind"):
        ReportOutline.from_json(payload)


def test_unknown_asset_kind_in_json_raises():
    payload = ReportOutline().to_json()
    payload["assets"]["X0001"] = {"kind": "video", "asset_id": "X0001"}
    with pytest.raises(ValueError, match="Unknown asset kind"):
        ReportOutline.from_json(payload)

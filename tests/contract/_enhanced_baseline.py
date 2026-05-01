"""Enhanced visual fixture — Phase 6 / 6.1.

Extends the ``normal`` baseline with every visual block variant the
renderers learned across Phases 1-5:

  - SectionCoverBlock (深色封面页)
  - KpiRowBlock at document head
  - ChartTablePairBlock (chart + table 双栏)
  - TableBlock with ``highlight_rules`` (rank<=3 / max / min / negative)
  - ComparisonGridBlock (短期/中期/长期 三栏建议)
  - ParagraphBlock with ``callout-warn`` / ``callout-info`` / ``lead``
  - GrowthIndicatorsBlock
  - Multiple chart kinds (bar + pie/doughnut)
  - Attribution-style table

The outline is built **directly** rather than via ``collect_and_associate``
so it can exercise blocks the legacy converter never produces. This is the
contract surface that Phase 6 visual regression / perceptual hash tests
also consume.
"""
from __future__ import annotations

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
    SectionCoverBlock,
    StatsAsset,
    TableAsset,
    TableBlock,
    reset_id_counters,
)


def make_enhanced_outline() -> ReportOutline:
    """Build a deterministic ``ReportOutline`` exercising every visual
    block. ID minting is reset so block / asset IDs stay stable across
    runs (B0001…, C0001…).
    """
    reset_id_counters()

    # ---- Assets --------------------------------------------------------

    bar_chart = ChartAsset(
        asset_id="C0001",
        source_task="T_THROUGHPUT",
        option={
            "title": {"text": "港区吞吐量"},
            "xAxis": {"type": "category", "data": ["大连港", "营口港", "锦州港"]},
            "yAxis": {"type": "value"},
            "series": [{
                "type": "bar",
                "data": [4500.5, 3200.1, 1800.0],
            }],
        },
        endpoint="throughput_by_region",
    )

    pie_chart = ChartAsset(
        asset_id="C0002",
        source_task="T_SHARE",
        option={
            "title": {"text": "市场份额"},
            "series": [{
                "type": "pie",
                "data": [
                    {"name": "大连港", "value": 4500.5},
                    {"name": "营口港", "value": 3200.1},
                    {"name": "锦州港", "value": 1800.0},
                ],
            }],
        },
        endpoint="share_by_region",
    )

    throughput_table = TableAsset(
        asset_id="T0001",
        source_task="T_THROUGHPUT",
        df_records=[
            {"regionName": "大连港", "throughput": 4500.5, "yoy": 0.12},
            {"regionName": "营口港", "throughput": 3200.1, "yoy": 0.05},
            {"regionName": "锦州港", "throughput": 1800.0, "yoy": -0.03},
        ],
        columns_meta=[
            {"name": "regionName"},
            {"name": "throughput"},
            {"name": "yoy"},
        ],
        endpoint="throughput_by_region",
    )

    attribution_table = TableAsset(
        asset_id="T0002",
        source_task="T_ATTRIBUTION",
        df_records=[
            {"factor": "船舶到港数", "contribution": 0.42},
            {"factor": "装卸效率",   "contribution": 0.31},
            {"factor": "天气因素",   "contribution": -0.08},
            {"factor": "其它",       "contribution": 0.05},
        ],
        columns_meta=[{"name": "factor"}, {"name": "contribution"}],
        endpoint="attribution_by_factor",
    )

    stats = StatsAsset(
        asset_id="S0001",
        source_task="T_THROUGHPUT",
        summary_stats={
            "throughput": {
                "max": 4500.5, "min": 1800.0, "mean": 3166.87, "std": 1102.3,
            },
        },
    )

    # ---- Sections ------------------------------------------------------

    summary = OutlineSection(
        name="一、执行摘要", role="summary",
        source_tasks=["T_THROUGHPUT"],
        blocks=[
            SectionCoverBlock(
                block_id="B0001", index=1, title="一、执行摘要",
                subtitle="2026 Q1 港区吞吐量整体回顾",
            ),
            ParagraphBlock(
                block_id="B0002",
                text=(
                    "2026 Q1 三港区合计吞吐量 9500.6 万吨，同比增长 12%。"
                    "大连港持续领跑，锦州港受天气拖累出现负增长。"
                ),
                style="lead",
            ),
        ],
    )

    status = OutlineSection(
        name="二、现状分析", role="status",
        source_tasks=["T_THROUGHPUT", "T_SHARE"],
        blocks=[
            SectionCoverBlock(
                block_id="B0003", index=2, title="二、现状分析",
                subtitle="吞吐量 + 市场份额双视角",
            ),
            ChartTablePairBlock(
                block_id="B0004",
                chart_asset_id="C0001",
                table_asset_id="T0001",
                layout="h",
            ),
            ChartBlock(
                block_id="B0005", asset_id="C0002",
                caption="市场份额分布",
            ),
            GrowthIndicatorsBlock(
                block_id="B0006",
                growth_rates={
                    "throughput": {"yoy": 0.12, "mom": 0.03},
                    "share":      {"yoy": 0.04, "mom": -0.01},
                },
            ),
        ],
    )

    attribution = OutlineSection(
        name="三、归因分析", role="attribution",
        source_tasks=["T_ATTRIBUTION"],
        blocks=[
            SectionCoverBlock(
                block_id="B0007", index=3, title="三、归因分析",
                subtitle="主要驱动因素拆解",
            ),
            TableBlock(
                block_id="B0008",
                asset_id="T0002",
                caption="归因贡献度",
                highlight_rules=[
                    {"col": "contribution", "predicate": "max",      "color": "positive"},
                    {"col": "contribution", "predicate": "negative", "color": "negative"},
                    {"col": "factor",       "predicate": "rank<=3",  "color": "accent"},
                ],
            ),
            ParagraphBlock(
                block_id="B0009",
                text="锦州港 yoy -3% 已连续两个季度走弱，需要警惕设备老化风险。",
                style="callout-warn",
            ),
            ParagraphBlock(
                block_id="B0010",
                text="装卸效率提升对总吞吐贡献 31%，推荐复制至其它港区。",
                style="callout-info",
            ),
        ],
    )

    recommendation = OutlineSection(
        name="四、行动建议", role="recommendation",
        source_tasks=[],
        blocks=[
            SectionCoverBlock(
                block_id="B0011", index=4, title="四、行动建议",
                subtitle="短期 / 中期 / 长期",
            ),
            ComparisonGridBlock(
                block_id="B0012",
                columns=[
                    GridColumn(title="短期 (Q2)", items=[
                        "锦州港启动设备巡检专项",
                        "复用大连港装卸 SOP",
                    ]),
                    GridColumn(title="中期 (H2)", items=[
                        "营口港运力扩张 +15%",
                        "天气联动调度系统上线",
                    ]),
                    GridColumn(title="长期 (2027+)", items=[
                        "三港区一体化调度",
                        "智能设备改造完成",
                    ]),
                ],
            ),
        ],
    )

    appendix = OutlineSection(
        name="附录：统计明细", role="appendix",
        source_tasks=["T_THROUGHPUT"],
        blocks=[
            TableBlock(
                block_id="B0013",
                asset_id="S0001",
                caption="统计数据概览",
            ),
        ],
    )

    return ReportOutline(
        metadata={
            "title":  "2026 Q1 港区吞吐量分析报告 (Enhanced)",
            "author": "Analytica Test",
            "date":   "2026-04-29",
            "intent": "全视觉特性回归 fixture",
        },
        kpi_summary=[
            KPIItem(label="总吞吐量", value="9500.6 万吨", sub="2026 Q1", trend="positive"),
            KPIItem(label="同比增长", value="12.0%",       sub="YoY",     trend="positive"),
            KPIItem(label="最高港区", value="大连港",       sub="4500.5 万吨", trend=None),
            KPIItem(label="负增长港", value="锦州港",       sub="-3.0%",       trend="negative"),
        ],
        sections=[summary, status, attribution, recommendation, appendix],
        assets={
            "C0001": bar_chart,
            "C0002": pie_chart,
            "T0001": throughput_table,
            "T0002": attribution_table,
            "S0001": stats,
        },
        planner_mode="llm",
    )

"""Step 8 — Outline planner LLM-path tests.

Stubs ``invoke_llm`` to return canned JSON, then verifies:
- Valid response → outline with planner_mode='llm'
- Invalid block kind → fallback
- Dangling asset_id → fallback
- Section count mismatch → fallback
- KPI summary parsed correctly
- Comparison grid parsed correctly
"""
from __future__ import annotations

import json

import pytest

from backend.tools.report._outline import (
    ChartBlock,
    ComparisonGridBlock,
    KpiRowBlock,
    ParagraphBlock,
    TableBlock,
)
from backend.tools.report._outline_planner import plan_outline

from tests.contract._report_baseline import (
    freeze_kpis,
    make_normal_fixture,
    override_settings,
)

pytestmark = pytest.mark.contract


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


def _stub_invoke_llm(monkeypatch, payload: dict | str) -> None:
    text = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else payload

    async def _stub(*args, **kwargs):
        return {"text": text}

    monkeypatch.setattr(
        "backend.tools.report._outline_planner.invoke_llm", _stub,
    )


def _valid_response_for_normal_fixture() -> dict:
    """Hand-crafted valid LLM response matching the normal fixture's
    3 sections + the assets that the legacy converter would create
    (T-prefix table, C-prefix chart, S-prefix stats)."""
    return {
        "kpi_summary": [
            {"label": "总吞吐量", "value": "9500万吨", "sub": "Q1", "trend": "positive"},
            {"label": "同比增长", "value": "12.0%", "sub": "YoY", "trend": "positive"},
        ],
        "sections": [
            {
                "name": "一、港区吞吐量现状",
                "role": "status",
                "source_tasks": ["T001", "T002"],
                "blocks": [
                    {"kind": "table", "asset_id": "T0001", "caption": "数据明细"},
                    {"kind": "chart", "asset_id": "C0001", "caption": "港区吞吐量"},
                ],
            },
            {
                "name": "二、关键指标分析",
                "role": "status",
                "source_tasks": ["T003"],
                "blocks": [
                    {"kind": "paragraph", "text": "营运分析", "style": "body"},
                    {"kind": "table", "asset_id": "S0001", "caption": "统计数据概览"},
                    {"kind": "growth_indicators",
                     "growth_rates": {"throughput": {"yoy": 0.12, "mom": 0.03}}},
                ],
            },
            {
                "name": "三、综合结论",
                "role": "recommendation",
                "source_tasks": ["T004"],
                "blocks": [
                    {"kind": "comparison_grid",
                     "columns": [
                         {"title": "短期", "items": ["监控吞吐量"]},
                         {"title": "中期", "items": ["扩容大连港"]},
                         {"title": "长期", "items": ["数字化升级"]},
                     ]},
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

async def test_valid_llm_response_yields_llm_mode(monkeypatch):
    _stub_invoke_llm(monkeypatch, _valid_response_for_normal_fixture())

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(
        params, ctx, task_order=params["_task_order"],
        intent=params.get("intent", ""),
    )

    assert outline.planner_mode == "llm"


async def test_llm_kpi_summary_parsed(monkeypatch):
    _stub_invoke_llm(monkeypatch, _valid_response_for_normal_fixture())

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    assert [k.label for k in outline.kpi_summary] == ["总吞吐量", "同比增长"]
    assert outline.kpi_summary[0].trend == "positive"


async def test_llm_blocks_constructed_correctly(monkeypatch):
    _stub_invoke_llm(monkeypatch, _valid_response_for_normal_fixture())

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    # Section 0 starts with an auto-injected SectionCoverBlock
    # (non-appendix sections always do); the LLM-emitted blocks follow.
    llm_blocks = [
        b for b in outline.sections[0].blocks if b.kind != "section_cover"
    ]
    llm_kinds = [b.kind for b in llm_blocks]
    assert llm_kinds == ["table", "chart"]
    assert isinstance(llm_blocks[0], TableBlock)
    assert llm_blocks[0].asset_id == "T0001"
    assert isinstance(llm_blocks[1], ChartBlock)


async def test_comparison_grid_parsed(monkeypatch):
    _stub_invoke_llm(monkeypatch, _valid_response_for_normal_fixture())

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    grid_blk = next(
        b for b in outline.sections[2].blocks
        if isinstance(b, ComparisonGridBlock)
    )
    assert [c.title for c in grid_blk.columns] == ["短期", "中期", "长期"]
    assert grid_blk.columns[0].items == ["监控吞吐量"]


async def test_section_role_preserved_from_input(monkeypatch):
    """LLM may echo a different role; we always overwrite with the
    inferred role from input section_definitions."""
    response = _valid_response_for_normal_fixture()
    response["sections"][0]["role"] = "appendix"  # try to override
    _stub_invoke_llm(monkeypatch, response)

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    assert outline.sections[0].role == "status"  # input wins


# ---------------------------------------------------------------------------
# Validation failures → fallback
# ---------------------------------------------------------------------------

async def test_dangling_asset_id_falls_back(monkeypatch):
    response = _valid_response_for_normal_fixture()
    response["sections"][0]["blocks"][0]["asset_id"] = "C9999"  # doesn't exist
    _stub_invoke_llm(monkeypatch, response)

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    assert outline.planner_mode == "rule_fallback"
    assert any(
        "C9999" in d.get("reason", "")
        for d in outline.degradations
    )


async def test_unknown_block_kind_falls_back(monkeypatch):
    response = _valid_response_for_normal_fixture()
    response["sections"][0]["blocks"].append({"kind": "doughnut"})
    _stub_invoke_llm(monkeypatch, response)

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    assert outline.planner_mode == "rule_fallback"
    assert any(
        "doughnut" in d.get("reason", "")
        for d in outline.degradations
    )


async def test_section_count_mismatch_falls_back(monkeypatch):
    response = _valid_response_for_normal_fixture()
    response["sections"].pop()  # 2 sections, input has 3
    _stub_invoke_llm(monkeypatch, response)

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    assert outline.planner_mode == "rule_fallback"
    assert any(
        "sections count mismatch" in d.get("reason", "")
        for d in outline.degradations
    )


# ---------------------------------------------------------------------------
# JSON parse robustness
# ---------------------------------------------------------------------------

async def test_response_in_markdown_code_fence_parsed(monkeypatch):
    payload = _valid_response_for_normal_fixture()
    _stub_invoke_llm(
        monkeypatch,
        f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```",
    )

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    assert outline.planner_mode == "llm"


async def test_synthesised_attribution_table_registered_as_asset(monkeypatch):
    """Phase 3.4 — LLM declares an attribution summary table via the
    ``synthesised_assets`` payload; block references resolve cleanly."""
    response = _valid_response_for_normal_fixture()
    response["synthesised_assets"] = [{
        "asset_id": "ATTR0001",
        "kind": "table",
        "source_task": "synthesised",
        "df_records": [
            {"问题": "投资支付滞后", "数据依据": "支付率 65%",
             "原因": "审批流程瓶颈", "影响": "项目交付延期",
             "责任方": "财务部"},
            {"问题": "设备完好率下降", "数据依据": "完好率 82%",
             "原因": "维护周期超期", "影响": "运营效率降低",
             "责任方": "运维部"},
        ],
        "columns_meta": [
            {"name": "问题"}, {"name": "数据依据"},
            {"name": "原因"}, {"name": "影响"}, {"name": "责任方"},
        ],
    }]
    # Reference the new asset from a section block
    response["sections"][2]["blocks"].append({
        "kind": "table", "asset_id": "ATTR0001", "caption": "归因汇总",
    })
    _stub_invoke_llm(monkeypatch, response)

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    assert outline.planner_mode == "llm"
    # Asset registered
    assert "ATTR0001" in outline.assets
    asset = outline.assets["ATTR0001"]
    assert asset.kind == "table"
    assert len(asset.df_records) == 2
    assert asset.df_records[0]["问题"] == "投资支付滞后"
    # Block referencing it survived
    sec3_table_blocks = [
        b for b in outline.sections[2].blocks
        if isinstance(b, TableBlock) and b.asset_id == "ATTR0001"
    ]
    assert len(sec3_table_blocks) == 1


async def test_synthesised_asset_with_dangling_reference_falls_back(monkeypatch):
    """Reference to an undeclared synthesised asset should fall back
    rather than render with an unresolved asset_id."""
    response = _valid_response_for_normal_fixture()
    response["sections"][2]["blocks"].append({
        "kind": "table", "asset_id": "ATTR9999", "caption": "缺失",
    })
    _stub_invoke_llm(monkeypatch, response)

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    assert outline.planner_mode == "rule_fallback"
    assert any(
        "ATTR9999" in d.get("reason", "") for d in outline.degradations
    )


async def test_response_with_think_tag_stripped(monkeypatch):
    payload = _valid_response_for_normal_fixture()
    _stub_invoke_llm(
        monkeypatch,
        f"<think>let me plan</think>\n{json.dumps(payload, ensure_ascii=False)}",
    )

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    assert outline.planner_mode == "llm"

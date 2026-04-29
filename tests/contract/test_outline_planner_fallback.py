"""Step 8 — Outline planner rule-fallback path tests.

When ``REPORT_OUTLINE_PLANNER_ENABLED`` is False (the default) or the
LLM path raises, ``plan_outline`` must produce a ReportOutline that's
byte-equivalent to the pre-Step-8 path
(``collect_and_build_outline`` + ``extract_kpis_llm``).
"""
from __future__ import annotations

import pytest

from backend.tools.report._outline import KpiRowBlock
from backend.tools.report._outline_planner import plan_outline

from tests.contract._report_baseline import (
    disable_skill_mode,
    freeze_kpis,
    make_normal_fixture,
    override_settings,
)

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def _baseline_env(monkeypatch):
    freeze_kpis(monkeypatch)
    disable_skill_mode(monkeypatch)


# ---------------------------------------------------------------------------
# Default (flag off) → rule path
# ---------------------------------------------------------------------------

async def test_plan_outline_uses_rule_fallback_when_flag_off(monkeypatch):
    """With REPORT_OUTLINE_PLANNER_ENABLED=False, planner_mode must be
    'rule_fallback' and no degradation marker should appear."""
    override_settings(
        monkeypatch,
        REPORT_AGENT_ENABLED=False,
        REPORT_OUTLINE_PLANNER_ENABLED=False,
    )

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(
        params, ctx,
        task_order=params.get("_task_order"),
        intent=params.get("intent", ""),
    )

    assert outline.planner_mode == "rule_fallback"
    assert all(
        d.get("kind") != "outline_planner_fallback"
        for d in outline.degradations
    )


async def test_rule_fallback_preserves_section_count_and_appendix(monkeypatch):
    override_settings(
        monkeypatch,
        REPORT_AGENT_ENABLED=False,
        REPORT_OUTLINE_PLANNER_ENABLED=False,
    )

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    # 3 input sections + 1 synthesised appendix
    assert len(outline.sections) == 4
    assert outline.sections[-1].role == "appendix"
    assert outline.sections[-1].name == "总结与建议"


async def test_rule_fallback_carries_kpi_summary(monkeypatch):
    override_settings(
        monkeypatch,
        REPORT_AGENT_ENABLED=False,
        REPORT_OUTLINE_PLANNER_ENABLED=False,
    )

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx)

    # _FROZEN_KPIS in the baseline fixture has 3 entries.
    assert len(outline.kpi_summary) == 3
    assert outline.kpi_summary[0].label == "总吞吐量"


# ---------------------------------------------------------------------------
# LLM failure → rule fallback with degradation marker
# ---------------------------------------------------------------------------

async def test_llm_failure_falls_back_with_degradation_marker(monkeypatch):
    override_settings(
        monkeypatch,
        REPORT_AGENT_ENABLED=False,
        REPORT_OUTLINE_PLANNER_ENABLED=True,
    )

    async def _stub_llm(*args, **kwargs):
        return {"error": "stub_failure", "error_category": "TEST"}

    monkeypatch.setattr(
        "backend.tools.report._outline_planner.invoke_llm", _stub_llm,
    )

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    assert outline.planner_mode == "rule_fallback"
    fallbacks = [
        d for d in outline.degradations
        if d.get("kind") == "outline_planner_fallback"
    ]
    assert len(fallbacks) == 1
    assert "stub_failure" in fallbacks[0]["reason"]


async def test_invalid_json_falls_back(monkeypatch):
    override_settings(
        monkeypatch,
        REPORT_AGENT_ENABLED=False,
        REPORT_OUTLINE_PLANNER_ENABLED=True,
    )

    async def _stub_llm(*args, **kwargs):
        return {"text": "not valid json {oops"}

    monkeypatch.setattr(
        "backend.tools.report._outline_planner.invoke_llm", _stub_llm,
    )

    params, ctx, _ = make_normal_fixture()
    outline = await plan_outline(params, ctx, task_order=params["_task_order"])

    assert outline.planner_mode == "rule_fallback"
    assert any(
        "not valid JSON" in d.get("reason", "")
        for d in outline.degradations
    )

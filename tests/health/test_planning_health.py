"""Planning layer minimum sanity check.

Two flavours:
  1. Static-input tests (no LLM) — verify parse + build + validate plumbing
     using a pre-formed JSON. These run instantly.
  2. Live-record-replay test — drives the actual LLM through `generate_plan`
     against a fixed intent. Cached so CI replays without LLM cost.

Refresh cache: `pytest tests/health/test_planning_health.py --llm-mode=record-missing`
"""
from __future__ import annotations

import json

import pytest

from backend.tools.loader import load_all_tools

pytestmark = pytest.mark.health


@pytest.fixture(scope="module", autouse=True)
def _load_tools():
    load_all_tools()


# ── Pure parsing / building (no LLM) ───────────────────────────


async def test_planning_parses_static_llm_output():
    """A well-formed plan JSON must round-trip through parse + build."""
    from backend.agent.planning import PlanningEngine, parse_planning_llm_output

    valid_plan_json = {
        "title": "smoke", "analysis_goal": "g", "estimated_duration": 10,
        "tasks": [
            {"task_id": "T001", "type": "data_fetch", "name": "fetch",
             "description": "", "depends_on": [], "tool": "tool_api_fetch",
             "params": {"endpoint_id": "getInvestPlanByYear"},
             "estimated_seconds": 5},
            {"task_id": "T002", "type": "visualization", "name": "chart",
             "description": "", "depends_on": ["T001"], "tool": "tool_chart_bar",
             "params": {}, "estimated_seconds": 5},
        ],
    }
    parsed = parse_planning_llm_output(json.dumps(valid_plan_json))
    assert parsed["title"] == "smoke"

    engine = PlanningEngine(llm=None, llm_timeout=10, max_retries=1)
    plan = engine._build_plan(parsed, complexity="chart_text", intent={"raw_query": "x"})
    assert plan.tasks
    assert plan.tasks[0].tool == "tool_api_fetch"


async def test_planning_handles_unparseable_output():
    """Garbage LLM output must raise PlanningError, not silently None."""
    from backend.agent.planning import parse_planning_llm_output
    from backend.exceptions import PlanningError

    with pytest.raises(PlanningError):
        parse_planning_llm_output("not json at all")


def test_planning_template_bypass_yields_valid_plan():
    """Template bypass path must produce a fully-loaded AnalysisPlan with
    `tool` field on every task (regression for skill→tool migration)."""
    from backend.agent.plan_templates import load_template

    plan = load_template("throughput_analyst")
    assert plan.tasks
    for t in plan.tasks:
        assert t.tool, f"task {t.task_id} missing tool field"


# ── Live record-replay: real planning LLM call ────────────────


async def test_generate_plan_via_recorded_llm(recorded_llm):
    """End-to-end planning: real LLM (or cached) → AnalysisPlan that
    survives the validator. Uses one canonical intent."""
    from backend.agent.planning import PlanningEngine
    from backend.agent.graph import build_llm  # patched

    intent = {
        "raw_query": "查 2026 年集装箱吞吐量",
        "analysis_goal": "查 2026 年集装箱吞吐量",
        "slots": {
            "analysis_subject": {"value": ["集装箱吞吐量"], "source": "user_input", "confirmed": True},
            "time_range": {
                "value": {"start": "2026-01-01", "end": "2026-12-31", "description": "2026年"},
                "source": "user_input", "confirmed": True,
            },
            "output_complexity": {"value": "simple_table", "source": "user_input", "confirmed": True},
            "domain": {"value": "D1", "source": "user_input", "confirmed": True},
        },
    }

    llm = build_llm("qwen3-235b", request_timeout=90)
    engine = PlanningEngine(llm=llm, llm_timeout=60.0, max_retries=2)
    plan = await engine.generate_plan(intent)

    assert plan.tasks, "planning produced empty plan"
    assert all(t.tool for t in plan.tasks), "some tasks missing tool field"

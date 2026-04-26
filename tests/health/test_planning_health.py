"""Planning layer minimum sanity check.

Goal: with a deterministic mock LLM, the planning engine produces a parseable,
validator-passing AnalysisPlan. Does NOT assert specific tasks or business
correctness — just plumbing.
"""
from __future__ import annotations

import json

import pytest

from backend.tools.loader import load_all_tools

pytestmark = pytest.mark.health


@pytest.fixture(scope="module", autouse=True)
def _load_tools():
    load_all_tools()


async def test_planning_parses_valid_llm_output(mock_llm):
    """A well-formed LLM JSON must round-trip to AnalysisPlan."""
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
    assert len(parsed["tasks"]) == 2

    # Build → validate
    engine = PlanningEngine(llm=mock_llm, llm_timeout=10, max_retries=1)
    plan = engine._build_plan(parsed, complexity="chart_text", intent={"raw_query": "x"})
    assert plan.tasks
    assert plan.tasks[0].tool == "tool_api_fetch"


async def test_planning_handles_unparseable_output():
    """Garbage LLM output must raise PlanningError, not silently return None."""
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

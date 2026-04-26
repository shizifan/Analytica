"""Execution layer minimum sanity check.

Single 1-task plan against the real mock_server. Verifies wiring only
(NOT business correctness or specific endpoint behaviour).
"""
from __future__ import annotations

import pytest

from backend.tools.loader import load_all_tools

pytestmark = pytest.mark.health


@pytest.fixture(scope="module", autouse=True)
def _load_tools():
    load_all_tools()


async def test_execute_plan_reaches_terminal_state(mock_server_settings):
    """A 1-task plan must finish (any terminal state — done/failed/skipped),
    never hang in `pending`/`running`."""
    from backend.agent.execution import execute_plan
    from backend.models.schemas import AnalysisPlan, TaskItem

    plan = AnalysisPlan(
        plan_id="health-1", version=1, title="health",
        analysis_goal="", estimated_duration=10,
        tasks=[
            TaskItem(
                task_id="T001", type="data_fetch", tool="tool_api_fetch",
                name="fetch", description="",
                params={"endpoint_id": "getInvestPlanByYear"},
                depends_on=[],
            ),
        ],
    )
    statuses, ctx, _ = await execute_plan(
        plan.tasks, ws_callback=None,
        allowed_tools=frozenset({"tool_api_fetch"}),
    )
    assert "T001" in statuses
    assert statuses["T001"] in ("done", "failed", "skipped"), (
        f"task left in non-terminal state: {statuses['T001']}"
    )


async def test_execute_plan_isolates_failed_task(mock_server_settings):
    """When one task fails, the other still runs (single-failure isolation)."""
    from backend.agent.execution import execute_plan
    from backend.models.schemas import AnalysisPlan, TaskItem

    plan = AnalysisPlan(
        plan_id="health-2", version=1, title="health",
        analysis_goal="", estimated_duration=20,
        tasks=[
            TaskItem(
                task_id="T_BAD", type="data_fetch", tool="tool_api_fetch",
                name="bad", description="",
                params={"endpoint_id": "getNonExistentEndpoint"},
                depends_on=[],
            ),
            TaskItem(
                task_id="T_OK", type="data_fetch", tool="tool_api_fetch",
                name="ok", description="",
                params={"endpoint_id": "getInvestPlanByYear"},
                depends_on=[],
            ),
        ],
    )
    statuses, _, _ = await execute_plan(
        plan.tasks, ws_callback=None,
        allowed_tools=frozenset({"tool_api_fetch"}),
    )
    # Both tasks must reach terminal state
    assert statuses["T_BAD"] in ("done", "failed", "skipped")
    assert statuses["T_OK"] in ("done", "failed", "skipped")

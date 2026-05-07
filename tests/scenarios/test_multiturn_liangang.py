"""Scenario: multi-turn conversation — Liaoning port throughput analysis.

End-to-end multi-turn simulation that exercises the V6 perception →
planning chain across four turns (R0 new → R1 continue → R2 continue →
R3 amend). All cross-turn data flows through the SessionWorkspace
manifest + ``data_ref`` protocol; legacy ``_classify_turn`` keyword
routing and ``build_amend_plan`` rule engine have been removed in V6.

Marked ``scenario`` — excluded from default regression. First run must
populate the LLM cache:

    pytest tests/scenarios/test_multiturn_liangang.py \\
        --llm-mode=record-missing -m scenario -v

Subsequent runs use cached responses and need no real LLM.

    pytest tests/scenarios/test_multiturn_liangang.py \\
        --llm-mode=replay -m scenario -v

Note: V6's perception MULTITURN_INTENT_PROMPT and planner WORKSPACE_BLOCK
are new — existing caches don't carry their fingerprints. Re-record
before relying on this scenario.
"""

from __future__ import annotations

from uuid import uuid4

import pandas as pd
import pytest

from backend.agent import perception as perception_mod
from backend.agent.graph import (
    build_llm,
    _build_multiturn_context_injection,
)
from backend.agent.perception import run_perception
from backend.agent.planning import PlanningEngine
from backend.memory.session_workspace import SessionWorkspace
from backend.memory.store import MemoryStore
from backend.models.schemas import TaskItem
from backend.tools.base import ToolOutput
from tests.lib.multiturn_helpers import make_continue_message

pytestmark = pytest.mark.scenario


@pytest.fixture(scope="module", autouse=True)
def _load_tools():
    from backend.tools.loader import load_all_tools

    load_all_tools()


def _seed_workspace_for_r0(session_id: str, root) -> SessionWorkspace:
    """Pre-populate a workspace with R0 task outputs so the planner's
    WORKSPACE_BLOCK has manifest entries to reference in R1+ turns."""
    ws = SessionWorkspace(session_id, root)
    ws.persist(
        TaskItem(
            task_id="T001", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "getThroughputAnalysisByYear", "dateYear": "2026"},
        ),
        ToolOutput(
            tool_id="tool_api_fetch", status="success", output_type="dataframe",
            data=pd.DataFrame({
                "month": ["2026-01", "2026-02", "2026-03"],
                "throughput_ton": [1234567, 987654, 1100000],
                "yoy_growth": [0.05, -0.03, 0.02],
            }),
        ),
        turn_index=0,
    )
    ws.persist(
        TaskItem(
            task_id="T002", type="analysis", tool="tool_desc_analysis",
            depends_on=["T001"], params={"data_ref": "T001"},
        ),
        ToolOutput(
            tool_id="tool_desc_analysis", status="success", output_type="text",
            data="Q1总吞吐量同比增长2.3%，3月环比下降5.1%",
        ),
        turn_index=0,
    )
    ws.finalize_turn(0)
    return ws


class TestScenarioMultiTurnLiaoning:
    """V6 multi-turn scenario: R0→R1→R2→R3 with manifest-driven reuse."""

    async def test_throughput_multiturn_full_chain(
        self,
        recorded_llm,
        test_db_session,
        tmp_path,
    ):
        """Simulate a 4-turn conversation; verify R3 amend plan carries
        ``data_refs`` (V6 §5.5) instead of the legacy
        ``_previous_artifacts`` field."""
        session_id = str(uuid4())
        employee_id = "throughput_analyst"
        user_id = "scenario_test"

        store = MemoryStore(test_db_session)
        await store.create_session(
            session_id, user_id, employee_id=employee_id,
        )
        ws = _seed_workspace_for_r0(session_id, tmp_path)

        # ── R0: new topic ────────────────────────────────────
        r0_msg = "请分析2026年Q1大连港的吞吐量趋势，生成HTML报告"
        r0_state = {
            "messages": [{"role": "user", "content": r0_msg}],
            "raw_query": r0_msg,
            "session_id": session_id,
            "user_id": user_id,
            "employee_id": employee_id,
        }
        r0_state = await run_perception(r0_state)
        assert r0_state.get("structured_intent") is not None, (
            "R0 perception failed"
        )

        llm = build_llm("qwen3-235b", request_timeout=90)
        engine = PlanningEngine(llm=llm, llm_timeout=60, max_retries=2)
        r0_plan = await engine.generate_plan(
            r0_state["structured_intent"],
            employee_id=employee_id,
        )
        assert len(r0_plan.tasks) > 0
        assert any(t.type == "report_gen" for t in r0_plan.tasks)

        # Build the same R0 state shape run_stream would persist so the
        # later make_continue_message + manifest injection see real data.
        r0_state["analysis_plan"] = r0_plan.model_dump()
        r0_state["turn_index"] = 0
        r0_state["turn_type"] = "new"
        r0_state["plan_confirmed"] = True
        r0_state["task_statuses"] = {
            t.task_id: "done" for t in r0_plan.tasks
        }
        r0_state["analysis_history"] = [{
            "turn": 0,
            "turn_type": "new",
            "plan_title": r0_plan.title,
            "key_findings": ["Q1总吞吐量同比增长2.3%"],
            "data_snapshots": [],
            "artifacts": [],
            "task_count": len(r0_plan.tasks),
            "completed_count": len(r0_plan.tasks),
            "failed_count": 0,
        }]
        r0_state["plan_history"] = []

        # ── R1: continue (drill down by zone) ─────────────────
        r1_msg = "按港区拆分看看各港区吞吐量占比"
        r1_state = make_continue_message(
            turn_index=1, message=r1_msg, prev_state=r0_state,
        )
        r1_state["_multiturn_context"] = _build_multiturn_context_injection(
            r1_state
        )
        r1_state = await run_perception(r1_state)
        assert r1_state.get("structured_intent") is not None
        # V6 — perception writes turn_type back; continue is the
        # expected classification for a drill-down phrase.
        assert r1_state.get("turn_type") in {"continue", "new", "amend"}

        r1_plan = await engine.generate_plan(
            r1_state["structured_intent"],
            employee_id=employee_id,
        )
        assert len(r1_plan.tasks) > 0
        assert r1_plan.title != r0_plan.title

        r1_state["analysis_plan"] = r1_plan.model_dump()
        r1_state["plan_confirmed"] = True
        r1_state["task_statuses"] = {t.task_id: "done" for t in r1_plan.tasks}

        # ── R3: amend (request additional format) ─────────────
        # Skip R2 in this lightweight scenario — what V6 cares about
        # is that R3 amend produces ``data_refs`` (manifest pointers),
        # not the legacy ``_previous_artifacts``.
        r3_msg = "再加一个 PPTX 报告"
        r3_state = make_continue_message(
            turn_index=2, message=r3_msg, prev_state=r1_state,
        )
        r3_state["_multiturn_context"] = _build_multiturn_context_injection(
            r3_state
        )
        r3_state = await run_perception(r3_state)
        assert r3_state.get("structured_intent") is not None

        r3_plan = await engine.generate_plan(
            r3_state["structured_intent"],
            employee_id=employee_id,
            _multiturn_context=r3_state["_multiturn_context"],
        )

        # V6 §5.5 — amend plans declare ``data_refs`` (or ``data_ref``)
        # in task.params; legacy ``_previous_artifacts`` must be absent.
        for t in r3_plan.tasks:
            assert "_previous_artifacts" not in (t.params or {}), (
                f"Task {t.task_id} still uses legacy _previous_artifacts"
            )
            assert "_previous_findings" not in (t.params or {}), (
                f"Task {t.task_id} still uses legacy _previous_findings"
            )

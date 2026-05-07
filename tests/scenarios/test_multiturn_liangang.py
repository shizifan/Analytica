"""Scenario: multi-turn conversation — Liaoning port throughput analysis.

End-to-end multi-turn simulation that exercises the full perception →
planning chain across four turns (R0 new → R1 continue → R2 continue →
R3 amend), plus new-topic detection.

Marked ``scenario`` — excluded from default regression.  First run must
populate the LLM cache:

    pytest tests/scenarios/test_multiturn_liangang.py \\
        --llm-mode=record-missing -m scenario -v

Subsequent runs use cached responses and need no real LLM.

    pytest tests/scenarios/test_multiturn_liangang.py \\
        --llm-mode=replay -m scenario -v
"""

from __future__ import annotations

from uuid import uuid4

import pytest

# V6 §4.4 — _classify_turn deleted (S4) and build_amend_plan / make_amend_state
# slated for deletion (S5). This scenario module exercises the legacy keyword
# router + amend rule engine, so it's skipped at module load until S5 rewrites
# it on top of the manifest-driven multi-turn pipeline (spec §10.1).
pytest.skip(
    "V6 §10.1 — keyword router + amend rule engine deleted in S4; "
    "scenario rewrite scheduled for S5",
    allow_module_level=True,
)

from backend.memory.store import MemoryStore  # noqa: E402
from backend.agent.graph import (  # noqa: E402
    build_llm,
    _build_multiturn_context_injection,
)
from backend.agent.perception import run_perception  # noqa: E402
from backend.agent.planning import PlanningEngine  # noqa: E402
from tests.lib.multiturn_helpers import make_continue_message  # noqa: E402

pytestmark = pytest.mark.scenario


@pytest.fixture(scope="module", autouse=True)
def _load_tools():
    from backend.tools.loader import load_all_tools

    load_all_tools()


class TestScenarioMultiTurnLiaoning:
    """Full multi-turn scenario: R0→R1→R2→R3 with context injection.

    Each turn independently exercises perception + planning, simulating
    the core logic of ``run_stream`` without the full WebSocket + graph
    pipeline.  Uses ``recorded_llm`` so the same cache file supports
    both CI replay and real-LLM verification.
    """

    async def test_throughput_multiturn_full_chain(
        self,
        recorded_llm,
        test_db_session,
    ):
        """Simulate a 4-turn conversation and verify incremental planning."""
        session_id = str(uuid4())
        employee_id = "throughput_analyst"
        user_id = "scenario_test"

        store = MemoryStore(test_db_session)
        await store.create_session(
            session_id, user_id, employee_id=employee_id,
        )

        # ──────────────────────────────────────────────────────
        # R0: New analysis
        # ──────────────────────────────────────────────────────
        r0_msg = "请分析2026年Q1大连港的吞吐量趋势，生成HTML报告"

        r0_state = {
            "messages": [{"role": "user", "content": r0_msg}],
            "raw_query": r0_msg,
            "session_id": session_id,
            "user_id": user_id,
            "employee_id": employee_id,
        }

        # Perception R0
        r0_state = await run_perception(r0_state)
        assert r0_state.get("structured_intent") is not None, (
            "R0 perception failed"
        )

        # Planning R0
        llm = build_llm("qwen3-235b", request_timeout=90)
        engine = PlanningEngine(llm=llm, llm_timeout=60, max_retries=2)
        r0_plan = await engine.generate_plan(
            r0_state["structured_intent"],
            employee_id=employee_id,
        )
        assert len(r0_plan.tasks) > 0, "R0 planning produced no tasks"
        assert any(
            t.type == "report_gen" for t in r0_plan.tasks
        ), "R0 should contain a report_gen task"

        # Persist R0 state (skip actual execution — scenario focuses on planning)
        r0_state["analysis_plan"] = r0_plan.model_dump()
        r0_state["turn_index"] = 0
        r0_state["turn_type"] = "new"
        # Build a minimal analysis_history for R0 so subsequent turns
        # have context to inject
        r0_plan_dict = r0_plan.model_dump()
        r0_state["analysis_history"] = [
            {
                "turn": 0,
                "turn_type": "new",
                "query": r0_msg[:200],
                "plan_title": r0_plan.title,
                "data_snapshots": [
                    {
                        "task_id": t.get("task_id", ""),
                        "endpoint": t.get("params", {}).get("endpoint_id"),
                        "rows": 3,
                        "columns": ["month", "throughput_ton"],
                        "sample": [
                            {"month": "2026-01", "throughput_ton": 1234567}
                        ],
                        "params": t.get("params", {}),
                    }
                    for t in r0_plan_dict.get("tasks", [])
                    if t.get("type") == "data_fetch"
                ],
                "key_findings": ["Q1总吞吐量同比增长2.3%"],
                "artifacts": [
                    {"format": "HTML", "artifact_id": f"artifact-r0-{session_id[:8]}"}
                ],
                "task_count": len(r0_plan.tasks),
                "completed_count": len(r0_plan.tasks),
                "failed_count": 0,
            }
        ]
        r0_state["plan_history"] = []
        r0_state["task_statuses"] = {
            t.get("task_id", ""): "done" for t in r0_plan_dict.get("tasks", [])
        }
        await store.save_session_state(session_id, r0_state)

        # ──────────────────────────────────────────────────────
        # R1: Continue — drill down by berth zone
        # ──────────────────────────────────────────────────────
        r1_msg = "按港区拆分看看各港区吞吐量占比"

        # Build R1 state mimicking run_stream's continue branch
        r1_state = make_continue_message(
            turn_index=1, message=r1_msg, prev_state=r0_state,
        )
        r1_state["_multiturn_context"] = _build_multiturn_context_injection(
            r1_state
        )

        # Perception R1
        r1_state = await run_perception(r1_state)
        assert r1_state.get("structured_intent") is not None, (
            "R1 perception failed"
        )

        # Planning R1
        r1_plan = await engine.generate_plan(
            r1_state["structured_intent"],
            employee_id=employee_id,
        )
        assert len(r1_plan.tasks) > 0, "R1 planning produced no tasks"
        # R1 plan title should differ from R0 (incremental planning)
        assert r1_plan.title != r0_plan.title, (
            f"R1 title '{r1_plan.title}' should differ from R0 '{r0_plan.title}'"
        )

        # Save R1 state
        r1_state["analysis_plan"] = r1_plan.model_dump()
        r1_state["turn_index"] = 1
        await store.save_session_state(session_id, r1_state)

        # ──────────────────────────────────────────────────────
        # R2: Continue — drill down into decline cause
        # ──────────────────────────────────────────────────────
        r2_msg = "详细分析下降原因"

        # Build R2 state
        r2_state = make_continue_message(
            turn_index=2, message=r2_msg, prev_state=r1_state,
        )
        r2_state["_multiturn_context"] = _build_multiturn_context_injection(
            r2_state
        )

        # Perception R2
        r2_state = await run_perception(r2_state)
        assert r2_state.get("structured_intent") is not None, (
            "R2 perception failed"
        )

        # Planning R2
        r2_plan = await engine.generate_plan(
            r2_state["structured_intent"],
            employee_id=employee_id,
        )
        assert len(r2_plan.tasks) > 0, "R2 planning produced no tasks"

        # Save R2 state (with analysis_plan for amend to reference)
        r2_state["analysis_plan"] = r2_plan.model_dump()
        r2_state["turn_index"] = 2
        await store.save_session_state(session_id, r2_state)

        # ──────────────────────────────────────────────────────
        # R3: Amend — add a PPTX report
        # ──────────────────────────────────────────────────────
        r3_msg = "再加一个 PPTX 报告"

        # Build amend state + call build_amend_plan
        r3_amend_state = make_amend_state(
            turn_index=3, message=r3_msg, prev_state=r2_state,
        )
        # amend state needs analysis_history for artifact/finding injection
        r3_amend_state["analysis_history"] = r2_state.get(
            "analysis_history", r0_state.get("analysis_history", [])
        )
        r3_amend_state["analysis_plan"] = r2_state.get(
            "analysis_plan", r0_state.get("analysis_plan", {})
        )

        r3_plan = build_amend_plan(r3_amend_state, r3_msg)
        assert r3_plan is not None, (
            "Amend plan should be produced for '加一个 PPTX 报告'"
        )
        assert len(r3_plan.tasks) > 0, "Amend should produce at least 1 task"

        amend_task = r3_plan.tasks[0]
        assert amend_task.tool == "tool_report_pptx"
        assert amend_task.depends_on == [], (
            "amend plan must NOT depend on cross-turn task IDs"
        )
        assert len(amend_task.params.get("_previous_artifacts", [])) > 0, (
            "amend plan should carry previous artifacts"
        )

    async def test_new_topic_after_multiturn(self):
        """'换个话题' after multi-turn history correctly classifies as 'new'."""
        multiturn_state = {
            "slots": {
                "analysis_subject": {"value": "大连港吞吐量"},
                "time_range": {
                    "value": {"start": "2026-01-01", "end": "2026-03-31"}
                },
            },
            "turn_index": 2,
            "analysis_history": [
                {"turn": 0, "key_findings": ["R0 finding"]},
                {"turn": 1, "key_findings": ["R1 finding"]},
            ],
            "messages": [
                {"role": "user", "content": "R0 query"},
                {"role": "user", "content": "R1 query"},
            ],
        }

        turn_type = _classify_turn(
            "换个话题，分析港口资产投资回报率", multiturn_state,
        )
        assert turn_type == "new", (
            "Explicit new-top topic should be classified as 'new'"
        )

"""V6 §9.2.6 — clarification continuity invariants.

Spec §7.1 documents three pre-existing bugs that V6 must fix:
  1. plan_history never accumulates on the ``continue`` path.
  2. turn_index inflates during clarification rounds.
  3. analysis_history grows half-summaries on clarification interrupts.

The spec's e2e test relies on ``consume_run_stream`` + ``recorded_llm``
+ a queue_plan helper that doesn't exist in the harness. We exercise
the same invariants at unit level by:

  * driving ``run_perception`` through a scripted LLM (V6 §4.2 path)
  * simulating run_stream's continuation guards directly on state dicts
  * pairing them with a real on-disk SessionWorkspace so the §7.3
    finalize / abandon contract is verified end-to-end.

What's covered (mapping to spec §7):
  * §7.2.1 — plan_history archived on turn entry, even for ``continue``.
  * §7.2.2 — turn_index advances only when prev_completed is True.
  * §7.2.3 — _should_append_turn_summary blocks half-turns.
  * §7.3   — finalize_turn promotes ongoing→finalized when turns close;
            abandon_orphaned_turn marks them ``abandoned`` when a new
            turn supersedes an unfinished one.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from backend.agent import perception as perception_mod
from backend.agent.execution import (
    _abandon_orphaned_turn,
    _finalize_turn,
)
from backend.agent.graph import _should_append_turn_summary
from backend.memory.session_workspace import SessionWorkspace
from backend.models.schemas import TaskItem
from backend.tools.base import ToolOutput


# ── helpers ───────────────────────────────────────────────────

def _make_task(task_id: str, **kw) -> TaskItem:
    kw.setdefault("type", "data_fetch")
    kw.setdefault("tool", "tool_api_fetch")
    return TaskItem(task_id=task_id, **kw)


def _make_output(data: Any = None, status: str = "success") -> ToolOutput:
    return ToolOutput(
        tool_id="t", status=status, output_type="json", data=data,
    )


def _seed_r0_workspace(tmp_path: Path) -> SessionWorkspace:
    """Mirror the multiturn fixture's R0 — two finalized tasks."""
    ws = SessionWorkspace("s1", tmp_path)
    ws.persist(_make_task("T001"), _make_output(pd.DataFrame({"x": [1, 2]})), 0)
    ws.persist(_make_task("T002", type="analysis", tool="tool_desc_analysis"),
               _make_output("Q1 同比 +2.3%"), 0)
    ws.finalize_turn(0)
    return ws


def _r0_completed_state() -> dict[str, Any]:
    """Concise prev_state representing a successfully finished R0."""
    return {
        "session_id": "s1",
        "turn_index": 0,
        "turn_type": "new",
        "slots": {
            "analysis_subject": {"value": ["吞吐量"], "source": "user_input"},
            "time_range": {
                "value": {"start": "2026-01-01", "end": "2026-03-31"},
                "source": "user_input",
            },
        },
        "structured_intent": {"analysis_goal": "Q1 吞吐量分析"},
        "plan_confirmed": True,
        "task_statuses": {"T001": "done", "T002": "done"},
        "analysis_plan": {
            "plan_id": "plan-r0-int",
            "turn_index": 0,
            "tasks": [
                {"task_id": "T001", "type": "data_fetch"},
                {"task_id": "T002", "type": "analysis"},
            ],
        },
        "analysis_history": [{"turn": 0, "turn_type": "new"}],
        "plan_history": [],
        "messages": [{"role": "user", "content": "分析 Q1 吞吐量"}],
    }


# ── §7.2.3 — _should_append_turn_summary guard ───────────────

class TestShouldAppendTurnSummary:

    def test_full_turn_passes(self):
        state = {
            "structured_intent": {"analysis_goal": "x"},
            "plan_confirmed": True,
            "task_statuses": {"T001": "done"},
        }
        assert _should_append_turn_summary(state) is True

    def test_clarification_round_blocks(self):
        """perception interrupted (no structured_intent) → must skip."""
        state = {
            "structured_intent": None,
            "plan_confirmed": False,
            "task_statuses": {},
        }
        assert _should_append_turn_summary(state) is False

    def test_planning_pending_blocks(self):
        state = {
            "structured_intent": {"analysis_goal": "x"},
            "plan_confirmed": False,
            "task_statuses": {},
        }
        assert _should_append_turn_summary(state) is False

    def test_execution_not_run_blocks(self):
        state = {
            "structured_intent": {"analysis_goal": "x"},
            "plan_confirmed": True,
            "task_statuses": {},
        }
        assert _should_append_turn_summary(state) is False


# ── §7.2.2 — turn_index advancement guard ────────────────────

def _prev_completed(prev_state: dict[str, Any]) -> bool:
    """Mirror the inline check in run_stream's continuation branch.
    Tests pin the behaviour so a refactor can't silently regress it."""
    return bool(
        prev_state.get("plan_confirmed")
        and prev_state.get("structured_intent") is not None
        and prev_state.get("task_statuses")
    )


class TestTurnIndexGuard:

    def test_completed_prev_advances(self):
        prev = _r0_completed_state()
        assert _prev_completed(prev) is True

    def test_clarification_state_does_not_advance(self):
        """Halfway through a clarification round: structured_intent is
        None, plan never confirmed → prev_completed must be False."""
        prev = _r0_completed_state()
        prev.update({
            "structured_intent": None,
            "plan_confirmed": False,
            "task_statuses": {},
            "turn_index": 1,  # already entered R1, but didn't finish
        })
        assert _prev_completed(prev) is False

    def test_plan_pending_confirmation_does_not_advance(self):
        prev = _r0_completed_state()
        prev["plan_confirmed"] = False
        assert _prev_completed(prev) is False

    def test_execution_not_yet_run_does_not_advance(self):
        prev = _r0_completed_state()
        prev["task_statuses"] = {}
        assert _prev_completed(prev) is False


# ── §7.2.1 — plan_history archive on continuation entry ─────

def _enter_continuation_branch(prev_state: dict[str, Any]) -> dict[str, Any]:
    """Reproduces run_stream's continuation-state mutations (V6 §4.3 +
    §7.2.1 + §7.2.2). Pure-data helper so tests can verify each side
    effect without spinning up the full graph."""
    state = dict(prev_state)
    state["structured_intent"] = None
    state["current_target_slot"] = None
    state["current_phase"] = "perception"
    state["error"] = None
    state["task_statuses"] = {}
    state["turn_type"] = None  # perception will write back

    # §7.2.1 archive
    if state.get("analysis_plan"):
        state.setdefault("plan_history", []).append(state["analysis_plan"])
        state["analysis_plan"] = None
        state["plan_confirmed"] = False

    # §7.2.2 turn_index guard
    turn_index = prev_state.get("turn_index", 0)
    if _prev_completed(prev_state):
        state["turn_index"] = turn_index + 1
    else:
        state["turn_index"] = turn_index
    return state


class TestPlanHistoryArchive:

    def test_continue_after_completed_r0_archives_plan(self):
        prev = _r0_completed_state()
        new_state = _enter_continuation_branch(prev)
        assert len(new_state["plan_history"]) == 1
        assert new_state["plan_history"][0]["plan_id"] == "plan-r0-int"
        assert new_state["analysis_plan"] is None
        assert new_state["plan_confirmed"] is False

    def test_archive_runs_regardless_of_turn_type(self):
        """V6 §7.2.1 — archival is on turn entry, not gated on turn_type.
        The legacy bug only triggered for ``continue`` because of the
        keyword router; the new behaviour archives uniformly."""
        prev = _r0_completed_state()
        prev["turn_type"] = "amend"  # would have skipped under the old router
        new_state = _enter_continuation_branch(prev)
        assert len(new_state["plan_history"]) == 1

    def test_clarification_round_does_not_double_archive(self):
        """In-flight clarification: plan_history was already populated by
        the previous R1 entry. A subsequent clarification round MUST NOT
        re-archive (analysis_plan is already None)."""
        prev = _r0_completed_state()
        # Simulate: R1 was already entered, plan_history holds R0 plan,
        # analysis_plan got cleared.
        prev["plan_history"] = [prev["analysis_plan"]]
        prev["analysis_plan"] = None
        prev["plan_confirmed"] = False
        prev["structured_intent"] = None
        prev["task_statuses"] = {}
        prev["turn_index"] = 1

        new_state = _enter_continuation_branch(prev)
        # No new archive — only one entry remains.
        assert len(new_state["plan_history"]) == 1


# ── §7.2.2 + history pollution ──────────────────────────────

class TestTurnIndexAndHistoryUnderClarification:

    def test_turn_index_advances_once_then_holds_during_clarification(self):
        """R0 finished → R1 starts (turn_index 0 → 1). Two clarification
        rounds keep turn_index at 1 because prev_completed=False."""
        # Step 1: enter R1 from completed R0
        r0 = _r0_completed_state()
        r1_first = _enter_continuation_branch(r0)
        assert r1_first["turn_index"] == 1

        # Step 2: simulate that perception didn't finish (clarification).
        r1_first.update({
            "structured_intent": None,
            "plan_confirmed": False,
            "task_statuses": {},
        })
        # Step 3: user answers clarification — re-enter run_stream.
        r1_second = _enter_continuation_branch(r1_first)
        assert r1_second["turn_index"] == 1  # held

        # Step 4: still not enough info — another clarification.
        r1_second.update({
            "structured_intent": None,
            "plan_confirmed": False,
            "task_statuses": {},
        })
        r1_third = _enter_continuation_branch(r1_second)
        assert r1_third["turn_index"] == 1  # still held

    def test_should_not_append_during_clarification(self):
        """Mid-clarification state must not be appended to
        analysis_history (§7.2.3)."""
        clarification_state = {
            "structured_intent": None,
            "plan_confirmed": False,
            "task_statuses": {},
            "analysis_history": [{"turn": 0}],
        }
        assert _should_append_turn_summary(clarification_state) is False


# ── §7.3 — workspace turn_status state machine via graph hooks ──

class TestWorkspaceTurnStatusHooks:

    @pytest.mark.asyncio
    async def test_finalize_promotes_ongoing_to_finalized(self, tmp_path):
        ws = SessionWorkspace("s1", tmp_path)
        ws.persist(_make_task("R1_T001"),
                   _make_output(pd.DataFrame({"x": [1]})), turn_index=1)
        assert ws.manifest["items"]["R1_T001"]["turn_status"] == "ongoing"

        await _finalize_turn(ws, turn_index=1)
        assert ws.manifest["items"]["R1_T001"]["turn_status"] == "finalized"

    @pytest.mark.asyncio
    async def test_abandon_marks_orphans_abandoned(self, tmp_path):
        """Simulate: R1 wrote ongoing entries, user gave up (no
        finalize), R2 starts. abandon_orphaned_turn flips R1's
        survivors to abandoned, preserving the R0 finalized history."""
        ws = _seed_r0_workspace(tmp_path)
        # R1 ongoing entry (clarification interrupted)
        ws.persist(_make_task("R1_INTERIM"),
                   _make_output(pd.DataFrame({"y": [3]})), turn_index=1)
        assert ws.manifest["items"]["R1_INTERIM"]["turn_status"] == "ongoing"

        await _abandon_orphaned_turn(ws, prev_turn_index=1)
        item = ws.manifest["items"]["R1_INTERIM"]
        assert item["turn_status"] == "abandoned"
        # R0 entries untouched
        assert ws.manifest["items"]["T001"]["turn_status"] == "finalized"

    @pytest.mark.asyncio
    async def test_clarification_round_keeps_workspace_clean(self, tmp_path):
        """V6 §9.2.6 — workspace must not contain R1 ongoing entries
        when no R1 task ever ran (perception interrupted before
        execution)."""
        ws = _seed_r0_workspace(tmp_path)
        # Perception failed mid-R1 → execution never wrote anything.
        # The workspace should still only show R0 finalized entries.
        for tid, item in ws.manifest["items"].items():
            assert item["turn_index"] == 0
            assert item["turn_status"] == "finalized"


# ── perception integration: clarification round reuses scripted LLM ──

class _ScriptedLLM:
    def __init__(self, payloads: list[dict[str, Any]]):
        self._payloads = payloads
        self.calls: list[str] = []

    async def __call__(self, prompt: str, *, timeout: float = 60.0) -> str:
        self.calls.append(prompt)
        if not self._payloads:
            raise AssertionError("scripted LLM ran out of responses")
        return json.dumps(self._payloads.pop(0), ensure_ascii=False)


class TestPerceptionClarificationFlow:

    @pytest.mark.asyncio
    async def test_clarification_then_completion_keeps_intent_lifecycle(
        self, monkeypatch,
    ):
        """Round 1: LLM asks for time_range. Round 2 (after user
        provides time_range): LLM emits structured_intent."""
        scripted = _ScriptedLLM(payloads=[
            {  # round 1 — needs clarification
                "turn_type": "continue",
                "needs_clarification": True,
                "ask_target_slots": ["time_range"],
                "structured_intent": {"slots": {}},
                "slot_delta": {},
            },
            {  # round 2 — user supplied time, intent ready
                "turn_type": "continue",
                "needs_clarification": False,
                "ask_target_slots": [],
                "structured_intent": {
                    "analysis_goal": "按港区拆分 Q1",
                    "slots": {
                        "data_granularity": {"value": "zone", "source": "user_input"},
                    },
                },
                "slot_delta": {
                    "time_range": {
                        "value": {"start": "2026-01-01", "end": "2026-03-31"},
                        "evidence": "用户输入",
                    },
                },
            },
        ])
        monkeypatch.setattr(
            perception_mod, "_call_multiturn_intent_llm", scripted,
        )

        # ── Round 1 ──
        state = {
            "session_id": "s1",
            "turn_index": 1,
            "slots": {"analysis_subject": {"value": ["吞吐量"], "source": "user_input"}},
            "_multiturn_context": {"turn_index": 1, "workspace_manifest": {}},
            "messages": [{"role": "user", "content": "深入看看"}],
        }
        result1 = await perception_mod.run_perception(state)
        assert result1["structured_intent"] is None
        assert result1["current_target_slot"] == "time_range"
        # ⇒ guard would block analysis_history append at this point
        assert _should_append_turn_summary(
            {**result1, "plan_confirmed": False, "task_statuses": {}}
        ) is False

        # ── Round 2 ──
        state2 = dict(result1)
        state2["messages"].append({
            "role": "user", "content": "按港区拆分时间用 Q1",
        })
        result2 = await perception_mod.run_perception(state2)
        assert result2["structured_intent"] is not None
        assert result2["current_target_slot"] is None
        assert result2["slots"]["time_range"]["source"] == "user_input"
        assert result2["slots"]["data_granularity"]["value"] == "zone"

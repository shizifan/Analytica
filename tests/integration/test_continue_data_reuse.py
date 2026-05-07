"""V6 §9.2.4 / §12 #5 — continue 数据复用.

A user asking "按港区拆分看看" must hit the manifest and reuse the
R0 ``T001`` DataFrame instead of re-fetching from the upstream API.
The verification is structural rather than behavioural — we don't
need a live tool registry; we just confirm that:

  1. The manifest already carries ``T001`` after R0.
  2. A continuation plan declaring ``data_ref="T001"`` resolves
     cleanly through ``_resolve_data_refs`` (i.e. the executor's
     pre-flight finds the entry in the workspace and skips the
     ``data_fetch`` task entirely).
  3. The workspace doesn't duplicate the manifest entry on a
     second persist call — V6 reuses the existing item rather than
     fetching again.

When this test starts failing, the most likely regression is that
``_resolve_data_refs`` no longer hits the manifest, or that the
planner/perception path stopped emitting ``data_ref`` and is making
the executor refetch.
"""
from __future__ import annotations

import pandas as pd
import pytest

from backend.agent.execution import _resolve_data_refs
from backend.exceptions import TaskError
from backend.memory.session_workspace import SessionWorkspace
from tests.lib.multiturn_helpers import make_task, seed_workspace


class TestContinueDataReuse:

    def test_manifest_contains_r0_data_after_first_turn(self, tmp_path):
        """After R0 persists, T001 lives in the manifest with
        ``status=done`` and ``turn_status=finalized`` — the planner's
        WORKSPACE_BLOCK shows it as a candidate for reuse."""
        ws = seed_workspace(
            tmp_path,
            items={"T001": pd.DataFrame({"x": list(range(10))})},
        )
        item = ws.manifest["items"]["T001"]
        assert item["status"] == "done"
        assert item["turn_status"] == "finalized"
        assert item["output_kind"] == "dataframe"

    @pytest.mark.asyncio
    async def test_continuation_data_ref_skips_redundant_fetch(self, tmp_path):
        """A continuation analysis task references R0's T001 via
        ``data_ref``. Pre-flight populates execution_context with the
        pre-fetched DataFrame; no second API call needed."""
        ws = seed_workspace(
            tmp_path,
            items={"T001": pd.DataFrame({
                "month": [f"2026-{i:02d}" for i in range(1, 4)],
                "throughput_ton": [1234567, 987654, 1100000],
            })},
        )
        analysis_task = make_task(
            "R1_ATTR",
            type="analysis",
            tool="tool_attribution",
            params={"data_ref": "T001"},
        )

        execution_context: dict = {}
        await _resolve_data_refs(analysis_task, execution_context, ws)

        # Pre-flight populated context — no need for a separate
        # data_fetch task on R1.
        loaded = execution_context["T001"]
        assert isinstance(loaded.data, pd.DataFrame)
        assert len(loaded.data) == 3
        assert list(loaded.data.columns) == ["month", "throughput_ton"]

    @pytest.mark.asyncio
    async def test_continuation_plan_can_mix_reuse_and_new_fetch(
        self, tmp_path,
    ):
        """A continuation plan may declare ``data_ref="T001"`` AND
        emit a new ``R1_T001`` task for fresh data. The reuse half
        resolves through manifest; the new fetch isn't visible to
        ``_resolve_data_refs`` (it's produced by the executor itself
        when its turn comes)."""
        ws = seed_workspace(
            tmp_path,
            items={"T001": pd.DataFrame({"x": [1, 2, 3]})},
        )
        compare_task = make_task(
            "R2_COMP",
            type="analysis",
            tool="tool_compare",
            params={"data_refs": ["T001", "R2_T001"]},  # mix — old + same-turn
        )

        # Same-turn upstream populated by the executor itself.
        execution_context: dict = {
            "R2_T001": _ok("from same-turn upstream"),
        }

        await _resolve_data_refs(compare_task, execution_context, ws)

        # T001 came from manifest, R2_T001 stayed put (in-context).
        assert "T001" in execution_context
        assert isinstance(execution_context["T001"].data, pd.DataFrame)
        assert execution_context["R2_T001"].data == "from same-turn upstream"

    @pytest.mark.asyncio
    async def test_unknown_ref_fails_fast_no_silent_refetch(self, tmp_path):
        """If the planner asks for an unknown ``data_ref``, the
        executor must NOT silently fall back to issuing a new fetch
        (V6 §11 R4). It must raise TaskError so the failure surfaces
        to the user / LLM and the next plan can fix it."""
        ws = SessionWorkspace("s1", tmp_path)
        task = make_task(
            "R1_X", type="analysis",
            params={"data_ref": "GHOST"},
        )
        with pytest.raises(TaskError, match="GHOST"):
            await _resolve_data_refs(task, {}, ws)

    def test_persist_overwrites_existing_entry_in_place(self, tmp_path):
        """If a turn re-runs and persists the same task_id, the
        manifest entry is updated rather than duplicated. Important
        for replay paths so the executor doesn't believe two
        independent products exist."""
        ws = SessionWorkspace("s1", tmp_path)
        ws.persist(
            make_task("T001"),
            _ok(pd.DataFrame({"x": [1, 2, 3]})),
            turn_index=0,
        )
        ws.persist(
            make_task("T001"),
            _ok(pd.DataFrame({"x": [10, 20, 30, 40]})),
            turn_index=0,
        )
        # Second persist overwrites the first row count.
        loaded = ws.load("T001")
        assert len(loaded.data) == 4

        # Only one manifest entry under "T001".
        keys = list(ws.manifest["items"].keys())
        assert keys.count("T001") == 1


# ── helpers ───────────────────────────────────────────────────

def _ok(data):
    from backend.tools.base import ToolOutput
    return ToolOutput(
        tool_id="t", status="success", output_type="json", data=data,
    )

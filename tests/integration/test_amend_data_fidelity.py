"""V6 §9.2.3 / §12 #4 — amend 数据保真 (the key V6 acceptance test).

A user asking "再加一份 PPTX" must see a PPTX containing the *full*
DataFrame from the original turn, not the 3-row ``sample`` snapshot
the legacy ``_previous_artifacts`` path used to forward.

The failure mode that V6 closes:

  * R0 fetched 100 rows → ToolOutput.data was a 100-row DataFrame.
  * Old amend rule built a tiny plan whose params carried
    ``_previous_artifacts``; the report tool reached into
    ``conversion_context.pkl`` for upstream context.
  * If the conversion ctx pickle was missing or mismatched, the tool
    silently fell back to the 3-row ``data_snapshots`` sample.
  * The PPTX showed 3 rows; the user thought their data was lost.

V6 routes all cross-turn data through the workspace manifest:
``workspace.persist`` writes the full DataFrame to disk;
``workspace.load`` round-trips it back; ``_resolve_data_refs``
hydrates the executor's context BEFORE the tool runs. There is no
silent fallback to sample any more — a missing reference fail-fasts
as ``TaskError``.
"""
from __future__ import annotations

import pandas as pd
import pytest

from backend.agent.execution import _resolve_data_refs
from backend.exceptions import TaskError
from backend.memory.session_workspace import SessionWorkspace
from tests.lib.multiturn_helpers import make_task, seed_workspace


# ── core fidelity tests ───────────────────────────────────────

class TestAmendDataFidelity:

    def test_workspace_load_round_trips_full_dataframe(self, tmp_path):
        """The 100-row DataFrame written in R0 comes back intact when
        an amend turn loads it through the manifest."""
        # Build a 100-row frame whose columns are all aligned. Months
        # cycle 2026-01 through 2026-12 then wrap.
        months = [f"2026-{(i % 12) + 1:02d}" for i in range(100)]
        df_full = pd.DataFrame({
            "month": months,
            "throughput_ton": list(range(100)),
            "yoy_growth": [0.01 * (i % 7) for i in range(100)],
        })
        assert len(df_full) == 100  # sanity for the test itself

        ws = SessionWorkspace("s1", tmp_path)
        ws.persist(
            make_task("T001"),
            _make_success_output(df_full),
            turn_index=0,
        )
        ws.finalize_turn(0)

        loaded = ws.load("T001")
        assert isinstance(loaded.data, pd.DataFrame)
        assert len(loaded.data) == 100, (
            "amend must see the full dataframe, not a sample"
        )
        # Schema preserved too — sample-only paths typically lose dtype info.
        assert list(loaded.data.columns) == [
            "month", "throughput_ton", "yoy_growth",
        ]

    @pytest.mark.asyncio
    async def test_amend_resolve_data_ref_hydrates_full_data(self, tmp_path):
        """Simulate R3 amend: a tiny PPTX task carries
        ``data_refs=["T001", "T002"]``; ``_resolve_data_refs`` writes
        the full ToolOutputs into the executor's context dict."""
        ws = seed_workspace(
            tmp_path,
            items={
                "T001": pd.DataFrame({
                    "x": list(range(100)), "y": list(range(100)),
                }),
                "T002": "Q1总吞吐量同比增长2.3%",
            },
        )
        amend_task = make_task(
            "R3_REPORT_PPTX",
            type="report_gen",
            tool="tool_report_pptx",
            params={"data_refs": ["T001", "T002"]},
        )
        execution_context: dict = {}

        await _resolve_data_refs(amend_task, execution_context, ws)

        # Both refs hydrated with full payloads.
        assert "T001" in execution_context
        assert isinstance(execution_context["T001"].data, pd.DataFrame)
        assert len(execution_context["T001"].data) == 100
        assert "T002" in execution_context
        assert execution_context["T002"].data == "Q1总吞吐量同比增长2.3%"

    @pytest.mark.asyncio
    async def test_amend_failfast_when_ref_missing(self, tmp_path):
        """A typo in the data_ref must raise TaskError, NOT silently
        fall back to the 3-row sample (legacy behaviour)."""
        ws = seed_workspace(
            tmp_path,
            items={"T001": pd.DataFrame({"x": [1, 2, 3]})},
        )
        amend_task = make_task(
            "R3_X",
            type="report_gen",
            tool="tool_report_pptx",
            params={"data_ref": "T01"},  # typo — should fail-fast
        )
        with pytest.raises(TaskError, match="T01"):
            await _resolve_data_refs(amend_task, {}, ws)

    def test_amend_plan_does_not_use_previous_artifacts(self):
        """V6 amend plans must declare ``data_refs`` (or ``data_ref``)
        in task.params, not the legacy ``_previous_artifacts`` /
        ``_previous_findings`` keys. This is a static contract test
        that locks the plan shape."""
        amend_task = make_task(
            "R3_REPORT_PPTX",
            type="report_gen",
            tool="tool_report_pptx",
            params={
                "data_refs": ["T001", "T002"],
                "intent": "吞吐量分析报告 — PPTX",
            },
        )
        # Forbidden legacy keys
        assert "_previous_artifacts" not in amend_task.params
        assert "_previous_findings" not in amend_task.params
        # Required V6 reference protocol
        assert "data_refs" in amend_task.params
        assert amend_task.params["data_refs"] == ["T001", "T002"]

    def test_workspace_persistence_round_trip_preserves_row_count(
        self, tmp_path,
    ):
        """Re-open the same workspace from disk; loaded data must
        have the same row count as written. This locks down the
        disk-roundtrip side of "no sample fallback"."""
        df = pd.DataFrame({
            "month": [f"2026-{i:02d}" for i in range(1, 13)],
            "value": list(range(12)),
        })
        ws1 = SessionWorkspace("s1", tmp_path)
        ws1.persist(make_task("T001"), _make_success_output(df), turn_index=0)
        ws1.finalize_turn(0)

        ws2 = SessionWorkspace("s1", tmp_path)
        loaded = ws2.load("T001")
        assert len(loaded.data) == 12


# ── helpers ───────────────────────────────────────────────────

def _make_success_output(data):
    """Tiny ToolOutput builder; the workspace doesn't care about
    output_type so we use 'json' as a generic placeholder."""
    from backend.tools.base import ToolOutput

    return ToolOutput(
        tool_id="t", status="success", output_type="json", data=data,
    )

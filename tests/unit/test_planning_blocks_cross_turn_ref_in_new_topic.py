"""Unit tests for V6 §6.1.3 hard constraint: new-mode plans must NOT
reference prior-turn manifest entries.

Spec §9.2.7's e2e test depends on a ``recorded_llm.queue_plan`` helper
that doesn't exist in the current LLM recorder. We achieve equivalent
coverage by exercising the validator directly with synthetic plans /
manifests, plus a smoke test for the prompt-rendering path so we catch
regressions in WORKSPACE_BLOCK output.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.agent.planning import (
    _render_manifest_summary_table,
    _render_workspace_block,
    validate_plan_against_workspace,
    WORKSPACE_BLOCK,
)
from backend.exceptions import PlanValidationError


# ── helpers ───────────────────────────────────────────────────

def _manifest(items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"session_id": "s1", "items": items}


def _entry(
    *, turn_index: int, status: str = "done",
    turn_status: str = "finalized",
    type_: str = "data_fetch", confirmed: bool = False,
    output_kind: str = "dataframe", path: str | None = "x.parquet",
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "task_id": "T?",
        "turn_index": turn_index,
        "type": type_,
        "tool": "tool_x",
        "status": status,
        "turn_status": turn_status,
        "user_confirmed": confirmed,
        "output_kind": output_kind,
        "path": path,
        "error": error,
        "rows": 100 if output_kind == "dataframe" else None,
        "preview": "Q1 同比增长 2.3%" if output_kind == "str" else None,
        "schema": {"columns": ["month", "value"], "dtypes": {}}
        if output_kind == "dataframe" else None,
    }


def _plan(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"tasks": tasks}


# ── new-mode hard constraint ──────────────────────────────────

class TestNewModeHardConstraint:

    def test_new_mode_rejects_cross_turn_data_ref(self):
        """turn_type=new + ref points at a previous turn's task → raise."""
        manifest = _manifest({"T001": _entry(turn_index=0)})
        plan = _plan([
            {
                "task_id": "R1_X", "type": "analysis", "tool": "tool_attribution",
                "params": {"data_ref": "T001"},
            }
        ])
        with pytest.raises(PlanValidationError, match="cross-turn data_ref.*T001"):
            validate_plan_against_workspace(
                plan,
                turn_type="new",
                current_turn_index=1,
                workspace_manifest=manifest,
            )

    def test_new_mode_rejects_data_refs_list(self):
        """data_refs (list form) — same rule applies, multiple offenders
        listed in the error."""
        manifest = _manifest({
            "T001": _entry(turn_index=0),
            "T002": _entry(turn_index=0),
        })
        plan = _plan([
            {
                "task_id": "R1_REPORT", "type": "report_gen",
                "tool": "tool_report_pptx",
                "params": {"data_refs": ["T001", "T002"]},
            }
        ])
        with pytest.raises(PlanValidationError) as exc_info:
            validate_plan_against_workspace(
                plan, turn_type="new", current_turn_index=1,
                workspace_manifest=manifest,
            )
        # offending_refs carries the full list; message lists both ids
        assert sorted(exc_info.value.offending_refs) == ["T001", "T002"]
        assert "T001" in str(exc_info.value)
        assert "T002" in str(exc_info.value)

    def test_new_mode_accepts_same_turn_internal_ref(self):
        """plan-internal DAG references stay legal in new mode."""
        manifest = _manifest({"T001": _entry(turn_index=0)})
        plan = _plan([
            {
                "task_id": "R1_FETCH", "type": "data_fetch",
                "tool": "tool_api_fetch",
                "params": {"endpoint_id": "ep_x"},
            },
            {
                "task_id": "R1_ATTR", "type": "analysis",
                "tool": "tool_attribution",
                "params": {"data_ref": "R1_FETCH"},
            },
        ])
        # No raise — R1_FETCH is produced inside the same plan.
        validate_plan_against_workspace(
            plan, turn_type="new", current_turn_index=1,
            workspace_manifest=manifest,
        )

    def test_new_mode_ignores_unknown_refs(self):
        """An unknown data_ref isn't a cross-turn violation; the
        execution layer fail-fasts on it at run time. Validator stays
        silent so we don't produce two error sources for the same
        symptom."""
        manifest = _manifest({"T001": _entry(turn_index=0)})
        plan = _plan([
            {
                "task_id": "R1_X", "type": "analysis", "tool": "tool_x",
                "params": {"data_ref": "GHOST"},
            }
        ])
        # No raise — execution layer will TaskError on GHOST.
        validate_plan_against_workspace(
            plan, turn_type="new", current_turn_index=1,
            workspace_manifest=manifest,
        )

    def test_continue_mode_allows_cross_turn_ref(self):
        manifest = _manifest({"T001": _entry(turn_index=0)})
        plan = _plan([
            {
                "task_id": "R1_X", "type": "analysis", "tool": "tool_x",
                "params": {"data_ref": "T001"},
            }
        ])
        # No raise.
        validate_plan_against_workspace(
            plan, turn_type="continue", current_turn_index=1,
            workspace_manifest=manifest,
        )

    def test_amend_mode_allows_cross_turn_ref(self):
        manifest = _manifest({"T001": _entry(turn_index=0)})
        plan = _plan([
            {
                "task_id": "R1_REPORT_PPTX", "type": "report_gen",
                "tool": "tool_report_pptx",
                "params": {"data_refs": ["T001"]},
            }
        ])
        validate_plan_against_workspace(
            plan, turn_type="amend", current_turn_index=1,
            workspace_manifest=manifest,
        )

    def test_empty_manifest_is_a_noop(self):
        plan = _plan([
            {
                "task_id": "R1_X", "type": "analysis", "tool": "tool_x",
                "params": {"data_ref": "T001"},
            }
        ])
        # No raise — manifest empty, nothing to violate against.
        validate_plan_against_workspace(
            plan, turn_type="new", current_turn_index=1,
            workspace_manifest={"session_id": "s1", "items": {}},
        )

    def test_turn_zero_never_violates(self):
        """First turn (index 0) cannot reference a previous turn — no
        previous turns exist."""
        manifest = _manifest({})
        plan = _plan([
            {
                "task_id": "T001", "type": "data_fetch", "tool": "tool_x",
                "params": {"endpoint_id": "ep"},
            }
        ])
        validate_plan_against_workspace(
            plan, turn_type="new", current_turn_index=0,
            workspace_manifest=manifest,
        )


# ── manifest summary rendering ────────────────────────────────

class TestManifestSummaryTable:

    def test_renders_dataframe_row_with_columns(self):
        manifest = _manifest({"T001": _entry(
            turn_index=0, type_="data_fetch", output_kind="dataframe",
        )})
        manifest["items"]["T001"]["task_id"] = "T001"
        manifest["items"]["T001"]["endpoint"] = "getThroughputAnalysisByYear"
        table = _render_manifest_summary_table(manifest, current_turn_index=1)
        assert "T001" in table
        assert "R0" in table
        assert "data_fetch" in table
        assert "100 行" in table  # row count surfaced

    def test_renders_failure_with_explicit_marker(self):
        manifest = _manifest({"T_FAIL": _entry(
            turn_index=0, status="failed", turn_status="finalized",
            output_kind="dataframe", path=None, error="endpoint timeout",
        )})
        manifest["items"]["T_FAIL"]["task_id"] = "T_FAIL"
        table = _render_manifest_summary_table(manifest, current_turn_index=1)
        assert "T_FAIL" in table
        assert "失败" in table
        assert "endpoint timeout" in table

    def test_skips_abandoned_entries(self):
        manifest = _manifest({
            "T_OK": _entry(turn_index=0),
            "T_ABANDONED": _entry(
                turn_index=0, turn_status="abandoned", status="done",
            ),
        })
        for tid in manifest["items"]:
            manifest["items"][tid]["task_id"] = tid
        table = _render_manifest_summary_table(manifest, current_turn_index=1)
        assert "T_OK" in table
        assert "T_ABANDONED" not in table

    def test_skips_cross_turn_ongoing(self):
        """ongoing entries from a turn other than current_turn_index do
        not surface — they're transient state, not durable products."""
        manifest = _manifest({
            "T_ONGOING_OLD": _entry(turn_index=0, turn_status="ongoing"),
            "T_ONGOING_CUR": _entry(turn_index=1, turn_status="ongoing"),
        })
        for tid in manifest["items"]:
            manifest["items"][tid]["task_id"] = tid
        table = _render_manifest_summary_table(manifest, current_turn_index=1)
        assert "T_ONGOING_OLD" not in table
        assert "T_ONGOING_CUR" in table

    def test_empty_manifest_renders_placeholder(self):
        table = _render_manifest_summary_table(
            {"session_id": "s1", "items": {}}, current_turn_index=1,
        )
        assert "暂无可引用产物" in table

    def test_folding_kicks_in_above_threshold(self):
        """Manifests above the fold threshold collapse older
        non-confirmed entries into a per-turn count line, while
        confirmed entries + recent two turns stay verbatim."""
        items: dict[str, dict[str, Any]] = {}
        # 25 items in turn 0 (above threshold but only one turn)
        for i in range(35):
            tid = f"T{i:03d}"
            items[tid] = _entry(turn_index=0)
            items[tid]["task_id"] = tid
        # 3 items in turn 1 (recent — keep) + 1 confirmed in turn 0
        items["T000"]["user_confirmed"] = True
        for i in range(3):
            tid = f"R1_T{i:03d}"
            items[tid] = _entry(turn_index=1)
            items[tid]["task_id"] = tid
        # Make turn_index span large enough that recent_turns excludes turn 0
        items["R2_X"] = _entry(turn_index=2)
        items["R2_X"]["task_id"] = "R2_X"

        table = _render_manifest_summary_table(
            _manifest(items), current_turn_index=2,
        )
        # confirmed entry stayed
        assert "T000" in table
        # turn 1 / 2 entries stayed (recent two turns)
        assert "R1_T000" in table
        assert "R2_X" in table
        # at least one folded line for turn 0 is present
        assert "已折叠" in table


# ── full WORKSPACE_BLOCK rendering ────────────────────────────

class TestWorkspaceBlock:

    def test_block_omitted_for_empty_manifest(self):
        block = _render_workspace_block(
            {"session_id": "s1", "items": {}},
            turn_index=1, turn_type="continue",
        )
        assert block == ""

    def test_block_includes_protocol_and_constraints(self):
        manifest = _manifest({"T001": _entry(turn_index=0)})
        manifest["items"]["T001"]["task_id"] = "T001"
        block = _render_workspace_block(
            manifest, turn_index=1, turn_type="continue",
        )
        assert "data_ref 协议" in block
        assert "本轮规划约束" in block
        assert "R1_" in block  # task_id prefix hint
        assert "turn_type=continue" in block

    def test_block_counts_total_and_confirmed(self):
        items = {
            "T001": _entry(turn_index=0, confirmed=True),
            "T002": _entry(turn_index=0, confirmed=False),
            "T003": _entry(turn_index=0, confirmed=True),
        }
        for tid in items:
            items[tid]["task_id"] = tid
        block = _render_workspace_block(
            _manifest(items), turn_index=1, turn_type="continue",
        )
        assert "共 3 项" in block
        assert "其中 2 项已被采纳" in block

    def test_workspace_block_constant_has_required_placeholders(self):
        """Smoke check on the prompt template — drift here usually
        means the spec text was edited but the renderer wasn't."""
        for placeholder in (
            "{total_items}", "{confirmed_count}", "{manifest_summary_table}",
            "{turn_idx}", "{turn_type}",
        ):
            assert placeholder in WORKSPACE_BLOCK

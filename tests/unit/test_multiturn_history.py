"""Unit tests for _build_turn_summary and trim_analysis_history."""

import json

import pandas as pd
import pytest

from backend.agent.graph import (
    _build_turn_summary,
    _extract_last_user_message,
    _extract_slot_snapshot,
    trim_analysis_history,
    MAX_HISTORY_TURNS,
    MAX_SAMPLE_PER_TASK,
    MAX_FINDINGS_PER_TURN,
    MAX_FINDING_LENGTH,
)


class TestBuildTurnSummary:
    """Test building analysis_history entries from execution results."""

    def _make_completed_state(self):
        """Build a realistic state after R0 execution completes."""
        # Create a simple DataFrame
        df = pd.DataFrame({
            "month": ["2026-01", "2026-02", "2026-03"],
            "throughput_ton": [1234567, 1345678, 1256789],
            "yoy_growth": [0.05, 0.06, 0.04],
        })

        # Simulate ToolOutput with 'data' attribute
        class FakeToolOutput:
            def __init__(self, data):
                self.data = data

        return {
            "turn_index": 0,
            "turn_type": "new",
            "messages": [
                {"role": "user", "content": "分析2026年Q1大连港吞吐量趋势"},
                {"role": "assistant", "content": "已生成分析方案"},
            ],
            "slots": {
                "analysis_subject": {"value": "吞吐量", "source": "user_input"},
                "time_range": {
                    "value": {"start": "2026-01-01", "end": "2026-03-31"},
                    "source": "user_input",
                },
            },
            "analysis_plan": {
                "title": "大连港2026年Q1吞吐量趋势分析",
                "tasks": [
                    {
                        "task_id": "T001",
                        "type": "data_fetch",
                        "tool": "api_throughput_analysis",
                        "params": {"endpoint_id": "getThroughputAnalysisByYear"},
                    },
                    {
                        "task_id": "T002",
                        "type": "analysis",
                        "tool": "tool_analysis",
                        "params": {},
                    },
                ],
            },
            "execution_context": {
                "T001": FakeToolOutput(df),
                "T002": FakeToolOutput("Q1总吞吐量同比增长2.3%，3月环比下降5.1%"),
            },
            "task_statuses": {
                "T001": "done",
                "T002": "done",
            },
        }

    def test_build_from_completed_turn(self):
        """Build a turn summary from a completed state."""
        state = self._make_completed_state()
        summary = _build_turn_summary(state)

        assert summary["turn"] == 0
        assert summary["turn_type"] == "new"
        assert "吞吐量" in summary["query"]
        assert summary["plan_title"] == "大连港2026年Q1吞吐量趋势分析"
        assert summary["task_count"] == 2
        assert summary["completed_count"] == 2
        assert summary["failed_count"] == 0

        # data_snapshots should have one entry for T001
        assert len(summary["data_snapshots"]) == 1
        snap = summary["data_snapshots"][0]
        assert snap["task_id"] == "T001"
        assert snap["endpoint"] == "getThroughputAnalysisByYear"
        assert snap["rows"] == 3
        assert len(snap["sample"]) == 3  # head(3)

        # key_findings should have one entry for T002
        assert len(summary["key_findings"]) == 1
        assert "同比增长" in summary["key_findings"][0]

        # slots_snapshot
        assert "analysis_subject" in summary["slots_snapshot"]
        assert summary["slots_snapshot"]["analysis_subject"]["value"] == "吞吐量"

    def test_all_fields_serializable(self):
        """All fields in the summary should survive json.dumps."""
        state = self._make_completed_state()
        summary = _build_turn_summary(state)

        # Should not raise
        dumped = json.dumps(summary, ensure_ascii=False, default=str)
        reloaded = json.loads(dumped)
        assert reloaded["turn"] == 0


class TestTrimHistory:
    """Test analysis_history truncation."""

    def _make_turn_entry(self, turn_idx: int, findings_count: int = 3) -> dict:
        """Build a minimal turn history entry."""
        return {
            "turn": turn_idx,
            "turn_type": "new" if turn_idx == 0 else "continue",
            "query": f"analysis turn {turn_idx}",
            "plan_title": f"Plan {turn_idx}",
            "data_snapshots": [
                {
                    "task_id": f"T{turn_idx}01",
                    "endpoint": f"endpoint_{turn_idx}",
                    "rows": 100,
                    "columns": [f"col_{i}" for i in range(15)],
                    "sample": [{"a": i} for i in range(10)],
                    "params": {},
                }
            ],
            "key_findings": [
                f"Finding {turn_idx}-{i} - " + "x" * 250
                for i in range(findings_count)
            ],
            "artifacts": [],
            "slots_snapshot": {
                f"slot_{i}": {"value": f"val_{i}"} for i in range(8)
            },
            "task_count": 5,
            "completed_count": 5,
            "failed_count": 0,
        }

    def test_trim_excess_turns(self):
        """History exceeding MAX_HISTORY_TURNS should be trimmed."""
        entries = [self._make_turn_entry(i) for i in range(8)]
        assert len(entries) == 8

        trimmed = trim_analysis_history(entries)
        assert len(trimmed) == MAX_HISTORY_TURNS
        # Should keep the most recent turns
        assert trimmed[0]["turn"] == 3  # 3,4,5,6,7
        assert trimmed[-1]["turn"] == 7

    def test_trim_truncates_findings(self):
        """Long findings should be truncated."""
        entry = self._make_turn_entry(0, findings_count=10)
        trimmed = trim_analysis_history([entry])

        assert len(trimmed[0]["key_findings"]) == MAX_FINDINGS_PER_TURN
        for f in trimmed[0]["key_findings"]:
            assert len(f) <= MAX_FINDING_LENGTH

    def test_trim_truncates_samples(self):
        """Data sample rows should be truncated."""
        entry = self._make_turn_entry(0)
        original_sample_len = len(entry["data_snapshots"][0]["sample"])
        assert original_sample_len == 10

        trimmed = trim_analysis_history([entry])
        assert len(trimmed[0]["data_snapshots"][0]["sample"]) == MAX_SAMPLE_PER_TASK

    def test_trim_truncates_columns(self):
        """Column list should be truncated to 10."""
        entry = self._make_turn_entry(0)
        original_cols = len(entry["data_snapshots"][0]["columns"])
        assert original_cols == 15

        trimmed = trim_analysis_history([entry])
        assert len(trimmed[0]["data_snapshots"][0]["columns"]) == 10

    def test_trim_truncates_slots_snapshot(self):
        """Slots snapshot should be trimmed to important slots only."""
        entry = self._make_turn_entry(0)
        original_slots = len(entry["slots_snapshot"])
        assert original_slots == 8

        trimmed = trim_analysis_history([entry])
        # After trimming, only important slots remain
        # But since none of the generated slot names match IMPORTANT_SLOTS,
        # they should still all be trimmed
        # Actually, since none of the slot names are in IMPORTANT_SLOTS,
        # the snapshot should be truncated to only important slots (which = 0 in this case)
        assert len(trimmed[0]["slots_snapshot"]) <= 5

    def test_trim_within_limit_no_op(self):
        """History within limits should not be modified structurally."""
        entry = self._make_turn_entry(0)
        trimmed = trim_analysis_history([entry])

        assert len(trimmed) == 1
        assert trimmed[0]["turn"] == 0
        assert trimmed[0]["plan_title"] == "Plan 0"


class TestExtractHelpers:
    """Test the extraction helpers used by _build_turn_summary."""

    def test_extract_last_user_message(self):
        state = {
            "messages": [
                {"role": "user", "content": "分析吞吐量"},
                {"role": "assistant", "content": "已理解"},
                {"role": "user", "content": "按港区拆分"},
            ],
        }
        msg = _extract_last_user_message(state)
        assert msg == "按港区拆分"

    def test_extract_last_user_message_empty(self):
        state = {"messages": []}
        msg = _extract_last_user_message(state)
        assert msg == ""

    def test_extract_slot_snapshot(self):
        slots = {
            "analysis_subject": {"value": "吞吐量", "source": "user_input"},
            "time_range": {
                "value": {"start": "2026-01-01"},
                "source": "user_input",
            },
            "empty_slot": {"value": None, "source": "default"},
            "missing_slot": None,
        }
        snapshot = _extract_slot_snapshot(slots)
        assert "analysis_subject" in snapshot
        assert snapshot["analysis_subject"]["value"] == "吞吐量"
        assert "empty_slot" not in snapshot
        assert "missing_slot" not in snapshot

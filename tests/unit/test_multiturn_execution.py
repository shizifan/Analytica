"""Unit tests for PR-2 execution.py multi-turn functions."""

import pytest
from unittest.mock import MagicMock

from backend.agent.execution import (
    _build_multiturn_execution_context,
    _should_skip_data_fetch,
    _params_match,
)
from backend.models.schemas import TaskItem


class TestBuildMultiturnExecutionContext:
    """Test _build_multiturn_execution_context from analysis_history."""

    def test_empty_history(self):
        ctx = _build_multiturn_execution_context({})
        assert ctx == {}

        ctx = _build_multiturn_execution_context({"analysis_history": []})
        assert ctx == {}

    def test_data_snapshots_mapped(self):
        state = {
            "analysis_history": [
                {
                    "turn": 0,
                    "turn_type": "new",
                    "data_snapshots": [
                        {
                            "task_id": "T001",
                            "endpoint": "api/throughput",
                            "rows": 100,
                            "columns": ["month", "throughput"],
                            "sample": [{"month": "Jan", "throughput": 1000}],
                            "params": {"dateYear": "2026"},
                        },
                    ],
                    "key_findings": ["Q1 throughput up 15%"],
                    "artifacts": [],
                }
            ]
        }
        ctx = _build_multiturn_execution_context(state)

        assert "T001" in ctx
        assert ctx["T001"]["_type"] == "data_snapshot"
        assert ctx["T001"]["endpoint"] == "api/throughput"
        assert ctx["T001"]["rows"] == 100
        assert ctx["T001"]["sample"] == [{"month": "Jan", "throughput": 1000}]

    def test_findings_injected(self):
        state = {
            "analysis_history": [
                {
                    "turn": 0,
                    "turn_type": "new",
                    "data_snapshots": [],
                    "key_findings": ["Finding A", "Finding B"],
                    "artifacts": [],
                }
            ]
        }
        ctx = _build_multiturn_execution_context(state)

        assert "R0_FINDINGS" in ctx
        assert ctx["R0_FINDINGS"]["_type"] == "findings"
        assert "Finding A" in ctx["R0_FINDINGS"]["text"]
        assert "Finding B" in ctx["R0_FINDINGS"]["text"]

    def test_multiple_turns(self):
        state = {
            "analysis_history": [
                {
                    "turn": 0,
                    "data_snapshots": [
                        {"task_id": "T001", "endpoint": "api/a", "sample": []},
                    ],
                    "key_findings": ["F0"],
                    "artifacts": [],
                },
                {
                    "turn": 1,
                    "data_snapshots": [
                        {"task_id": "T002", "endpoint": "api/b", "sample": []},
                    ],
                    "key_findings": ["F1"],
                    "artifacts": [],
                },
            ]
        }
        ctx = _build_multiturn_execution_context(state)

        assert "T001" in ctx
        assert "T002" in ctx
        assert "R0_FINDINGS" in ctx
        assert "R1_FINDINGS" in ctx


class TestParamsMatch:
    """Test _params_match for semantic parameter comparison."""

    def test_exact_match(self):
        p1 = {"dateYear": "2026", "regionName": "大连"}
        p2 = {"dateYear": "2026", "regionName": "大连"}
        assert _params_match(p1, p2) is True

    def test_different_key_param(self):
        p1 = {"dateYear": "2026"}
        p2 = {"dateYear": "2025"}
        assert _params_match(p1, p2) is False

    def test_ignore_non_key_params(self):
        """Only key_params (date, region, etc.) are compared; format/sort ignored."""
        p1 = {"dateYear": "2026", "format": "json", "sort": "asc"}
        p2 = {"dateYear": "2026", "format": "csv", "sort": "desc"}
        assert _params_match(p1, p2) is True

    def test_empty_dicts(self):
        assert _params_match({}, {}) is True

    def test_only_one_has_key(self):
        p1 = {"dateYear": "2026", "regionName": "大连"}
        p2 = {}
        assert _params_match(p1, p2) is False

    def test_one_has_dateyear_other_not(self):
        p1 = {"dateYear": "2026"}
        p2 = {"dateMonth": "03"}
        # dateYear exists in p1 but not p2 → p2.get("dateYear")=None → not equal
        assert _params_match(p1, p2) is False

    def test_no_overlapping_key_params(self):
        """When neither dict has any key_params, they match trivially."""
        p1 = {"format": "json"}
        p2 = {"sort": "asc"}
        assert _params_match(p1, p2) is True


class TestShouldSkipDataFetch:
    """Test _should_skip_data_fetch for duplicate API call detection."""

    def _make_task(self, **kwargs):
        defaults = {
            "task_id": "T001",
            "type": "data_fetch",
            "name": "Fetch Data",
            "tool": "tool_data_fetch",
            "params": {"endpoint_id": "api/throughput", "dateYear": "2026"},
            "depends_on": [],
        }
        defaults.update(kwargs)
        return TaskItem(**defaults)

    def _make_snapshots(self, snapshots):
        return [
            {"turn": i, **s} for i, s in enumerate(snapshots)
        ]

    def test_no_snapshots(self):
        task = self._make_task()
        assert _should_skip_data_fetch(task, []) is False
        assert _should_skip_data_fetch(task, None) is False

    def test_matching_endpoint_and_params(self):
        task = self._make_task(
            params={"endpoint_id": "api/throughput", "dateYear": "2026"},
        )
        snaps = self._make_snapshots([
            {
                "endpoint": "api/throughput",
                "params": {"dateYear": "2026", "format": "json"},
                "task_id": "R0_T001",
            },
        ])
        assert _should_skip_data_fetch(task, snaps) is True

    def test_different_endpoint(self):
        task = self._make_task(
            params={"endpoint_id": "api/throughput", "dateYear": "2026"},
        )
        snaps = self._make_snapshots([
            {
                "endpoint": "api/revenue",
                "params": {"dateYear": "2026"},
                "task_id": "R0_T001",
            },
        ])
        assert _should_skip_data_fetch(task, snaps) is False

    def test_different_date_param(self):
        task = self._make_task(
            params={"endpoint_id": "api/throughput", "dateYear": "2026"},
        )
        snaps = self._make_snapshots([
            {
                "endpoint": "api/throughput",
                "params": {"dateYear": "2025"},
                "task_id": "R0_T001",
            },
        ])
        assert _should_skip_data_fetch(task, snaps) is False

    def test_multiple_snapshots_finds_match(self):
        task = self._make_task(
            params={"endpoint_id": "api/target", "regionName": "大连"},
        )
        snaps = self._make_snapshots([
            {
                "endpoint": "api/other",
                "params": {"dateYear": "2026"},
                "task_id": "R0_T001",
            },
            {
                "endpoint": "api/target",
                "params": {"regionName": "大连"},
                "task_id": "R1_T002",
            },
        ])
        assert _should_skip_data_fetch(task, snaps) is True

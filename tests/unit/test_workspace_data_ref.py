"""Unit tests for backend.agent.execution._resolve_data_refs and the
``_persist_task_to_workspace`` hook.

Mirrors V6 spec §9.2.2. Same helper conventions as
``test_session_workspace.py`` — local ``make_task`` / ``make_output``
shorthand because backend.tools.base.ToolOutput requires extra fields
the spec text omits.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from backend.agent.execution import (
    _persist_task_to_workspace,
    _resolve_data_refs,
)
from backend.exceptions import TaskError
from backend.memory.session_workspace import SessionWorkspace
from backend.models.schemas import TaskItem
from backend.tools.base import ToolOutput


# ── helpers ───────────────────────────────────────────────────

def make_task(
    task_id: str,
    *,
    type: str = "data_fetch",
    tool: str = "tool_api_fetch",
    depends_on: list[str] | None = None,
    name: str = "",
    params: dict[str, Any] | None = None,
) -> TaskItem:
    return TaskItem(
        task_id=task_id,
        type=type,  # type: ignore[arg-type]
        tool=tool,
        depends_on=depends_on or [],
        name=name,
        params=params or {},
    )


def make_output(
    data: Any = None,
    *,
    status: str = "success",
    error: str | None = None,
    output_type: str = "json",
    tool_id: str = "test_tool",
) -> ToolOutput:
    return ToolOutput(
        tool_id=tool_id,
        status=status,
        output_type=output_type,
        data=data,
        error_message=error,
    )


def seed_workspace(tmp_path: Path, items: dict[str, Any]) -> SessionWorkspace:
    """Create a workspace under ``tmp_path`` and persist each item under
    its key as ``task_id``. Values may be any persistable type."""
    ws = SessionWorkspace("s1", tmp_path)
    for task_id, data in items.items():
        ws.persist(make_task(task_id), make_output(data, status="done"), turn_index=0)
    return ws


# ── data_ref resolution ───────────────────────────────────────

class TestResolveDataRefs:

    async def test_loads_single_ref_from_workspace(self, tmp_path):
        """task 引用前轮 task_id，execution 自动从 workspace 加载."""
        ws = seed_workspace(tmp_path, items={"T001": pd.DataFrame({"x": [1, 2, 3]})})
        task = make_task("R1_ATTR", params={"data_ref": "T001"})
        execution_context: dict[str, ToolOutput] = {}

        await _resolve_data_refs(task, execution_context, ws)

        assert "T001" in execution_context
        loaded = execution_context["T001"]
        assert isinstance(loaded.data, pd.DataFrame)
        assert len(loaded.data) == 3

    async def test_loads_multiple_refs_via_data_refs_list(self, tmp_path):
        """data_refs 列表形式同时解析多个."""
        ws = seed_workspace(tmp_path, items={
            "T001": pd.DataFrame({"x": [1]}),
            "T002": "Q1 同比增长 2.3%",
        })
        task = make_task("R1_REPORT", params={"data_refs": ["T001", "T002"]})
        ec: dict[str, ToolOutput] = {}

        await _resolve_data_refs(task, ec, ws)

        assert {"T001", "T002"} <= set(ec)
        assert isinstance(ec["T001"].data, pd.DataFrame)
        assert ec["T002"].data == "Q1 同比增长 2.3%"

    async def test_failfast_on_missing_ref(self, tmp_path):
        ws = SessionWorkspace("s1", tmp_path)
        task = make_task("R1_X", params={"data_ref": "GHOST"})
        with pytest.raises(TaskError, match="GHOST"):
            await _resolve_data_refs(task, {}, ws)

    async def test_skips_when_already_in_context(self, tmp_path):
        """同轮上游已产出的不重新加载——执行上下文里已有的不被 manifest 覆盖."""
        ws = SessionWorkspace("s1", tmp_path)
        task = make_task("R1_DOWN", params={"data_ref": "R1_UP"})
        upstream = make_output("from upstream", status="success")
        ec: dict[str, ToolOutput] = {"R1_UP": upstream}

        await _resolve_data_refs(task, ec, ws)

        assert ec["R1_UP"] is upstream  # untouched
        assert ec["R1_UP"].data == "from upstream"

    async def test_no_refs_is_a_noop(self, tmp_path):
        """task 不声明 data_ref 时直接返回，不查 manifest."""
        ws = SessionWorkspace("s1", tmp_path)
        task = make_task("T_LONELY")
        ec: dict[str, ToolOutput] = {}
        await _resolve_data_refs(task, ec, ws)
        assert ec == {}

    async def test_combines_data_ref_and_data_refs(self, tmp_path):
        """同时提供单值和列表——都要解析."""
        ws = seed_workspace(tmp_path, items={
            "T001": pd.DataFrame({"x": [1]}),
            "T002": pd.DataFrame({"y": [2]}),
            "T003": pd.DataFrame({"z": [3]}),
        })
        task = make_task(
            "R1_MERGE",
            params={"data_ref": "T001", "data_refs": ["T002", "T003"]},
        )
        ec: dict[str, ToolOutput] = {}
        await _resolve_data_refs(task, ec, ws)
        assert {"T001", "T002", "T003"} <= set(ec)

    async def test_ignores_non_string_ref_values(self, tmp_path):
        """data_refs 中混入 None / int 等非字符串项 → 忽略，不抛错."""
        ws = seed_workspace(tmp_path, items={"T001": pd.DataFrame({"x": [1]})})
        task = make_task(
            "R1_X",
            params={"data_refs": ["T001", None, 123, ""]},
        )
        ec: dict[str, ToolOutput] = {}
        await _resolve_data_refs(task, ec, ws)
        assert "T001" in ec


# ── persist hook ──────────────────────────────────────────────

class TestPersistHook:

    async def test_success_lands_in_manifest(self, tmp_path):
        ws = SessionWorkspace("s1", tmp_path)
        task = make_task("T001")
        output = make_output(pd.DataFrame({"x": [1, 2]}), status="success")

        await _persist_task_to_workspace(task, output, {"turn_index": 0}, ws)

        item = ws.manifest["items"]["T001"]
        assert item["status"] == "done"
        assert item["turn_index"] == 0
        assert item["output_kind"] == "dataframe"

    async def test_failed_status_records_failure_entry(self, tmp_path):
        ws = SessionWorkspace("s1", tmp_path)
        task = make_task("T_FAIL")
        output = make_output(None, status="failed", error="endpoint timeout")

        # Failure does NOT raise — the task already failed upstream;
        # persist just preserves the audit trail.
        await _persist_task_to_workspace(task, output, {"turn_index": 0}, ws)

        item = ws.manifest["items"]["T_FAIL"]
        assert item["status"] == "failed"
        assert item["path"] is None
        assert "endpoint timeout" in (item.get("error") or "")

    async def test_unserializable_raises_task_error(self, tmp_path):
        """Serialization-time failure must surface as TaskError so the
        executor flips the task itself to failed (V6 §11 R2)."""
        ws = SessionWorkspace("s1", tmp_path)
        task = make_task("T_BAD")
        bad: dict[str, Any] = {}
        bad["self"] = bad
        output = make_output(bad, status="success")

        with pytest.raises(TaskError, match="无法序列化|unserializable"):
            await _persist_task_to_workspace(task, output, {"turn_index": 0}, ws)

        # Manifest entry still exists for audit (V6 失败显式化)
        item = ws.manifest["items"]["T_BAD"]
        assert item["status"] == "unserializable"

    async def test_turn_index_threaded_to_manifest(self, tmp_path):
        ws = SessionWorkspace("s1", tmp_path)
        task = make_task("R3_T001")
        await _persist_task_to_workspace(
            task, make_output(pd.DataFrame({"x": [1]}), status="success"),
            {"turn_index": 3}, ws,
        )
        assert ws.manifest["items"]["R3_T001"]["turn_index"] == 3

    async def test_default_turn_index_when_missing_from_state(self, tmp_path):
        """state 不含 turn_index 时退回 0."""
        ws = SessionWorkspace("s1", tmp_path)
        await _persist_task_to_workspace(
            make_task("T_NO_TURN"),
            make_output(pd.DataFrame({"x": [1]}), status="success"),
            {}, ws,
        )
        assert ws.manifest["items"]["T_NO_TURN"]["turn_index"] == 0


# ── executor integration ──────────────────────────────────────

class TestExecutorIntegration:
    """End-to-end through ``_execute_single_task`` to verify the hook
    is wired into the real task runner. Uses a tiny in-memory tool to
    avoid depending on the real tool registry."""

    async def test_resolve_data_ref_failure_marks_task_failed(self, tmp_path):
        """Tool with an unresolvable data_ref must short-circuit before
        the tool runs, surfacing a failed ToolOutput."""
        from backend.agent.execution import _execute_single_task
        from backend.tools.registry import ToolRegistry
        from backend.tools.base import BaseTool

        ws = SessionWorkspace("s1", tmp_path)

        class _DummyTool(BaseTool):
            tool_id = "dummy_v6_test"

            async def execute(self, inp, context):
                return ToolOutput(
                    tool_id=self.tool_id, status="success",
                    output_type="json", data={"ok": True},
                )

        registry = ToolRegistry.get_instance()
        registry.register(_DummyTool())

        task = make_task("R1_X", tool="dummy_v6_test", params={"data_ref": "GHOST"})
        tid, output = await _execute_single_task(
            task, context={}, workspace=ws,
        )

        assert tid == "R1_X"
        assert output.status == "failed"
        assert output.metadata.get("error_category") == "WORKSPACE_REF_MISSING"
        assert "GHOST" in (output.error_message or "")

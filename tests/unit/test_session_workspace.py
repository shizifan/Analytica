"""Unit tests for backend.memory.session_workspace.SessionWorkspace.

Mirrors V6 spec §9.2.1. Two intentional deviations from the spec text:

  1. ``ToolOutput`` has no ``error`` field — the canonical attribute is
     ``error_message``. The local ``make_output`` helper translates the
     spec's ``error="..."`` shorthand into the right field.
  2. ``persist`` raises ``WorkspaceSerializationError`` for the
     unserializable case (per S1 手册 / spec §11 R8) — the spec §9.2.1
     example omits the ``pytest.raises`` wrapper but the surrounding text
     mandates exception propagation. The test asserts both the raise and
     the manifest's ``status="unserializable"`` snapshot.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from backend.exceptions import WorkspaceError, WorkspaceSerializationError
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
    """ToolOutput builder. Maps spec's ``error=`` shorthand to ``error_message``."""
    return ToolOutput(
        tool_id=tool_id,
        status=status,
        output_type=output_type,
        data=data,
        error_message=error,
    )


# ── persistence ───────────────────────────────────────────────

class TestSessionWorkspace:

    def test_persist_dataframe_as_parquet(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        df = pd.DataFrame({"month": ["2026-01"], "value": [100]})
        task = make_task("T001", type="data_fetch", tool="tool_api_fetch")
        ws.persist(task, make_output(df, status="done"), turn_index=0)

        assert (tmp_path / "s1" / "workspace" / "T001.parquet").exists()
        item = ws.manifest["items"]["T001"]
        assert item["output_kind"] == "dataframe"
        assert item["rows"] == 1
        assert item["schema"]["columns"] == ["month", "value"]
        assert item["status"] == "done"
        assert item["turn_status"] == "ongoing"

    def test_persist_str_as_txt(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        task = make_task("T002", type="analysis", tool="tool_desc_analysis")
        ws.persist(task, make_output("同比增长2.3%", status="done"), turn_index=0)

        item = ws.manifest["items"]["T002"]
        assert item["output_kind"] == "str"
        assert item["preview"] == "同比增长2.3%"
        assert (tmp_path / "s1" / "workspace" / "T002.txt").exists()

    def test_persist_dict_as_json(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        task = make_task("T003", type="analysis", tool="tool_kpi")
        ws.persist(task, make_output({"kpi": 0.92, "name": "增长率"}, status="done"), 0)

        item = ws.manifest["items"]["T003"]
        assert item["output_kind"] == "json"
        assert (tmp_path / "s1" / "workspace" / "T003.json").exists()

    def test_persist_bytes_as_bin(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        task = make_task("T_BIN", type="report_gen", tool="tool_report_html")
        ws.persist(task, make_output(b"<html></html>", status="done"), 0)

        item = ws.manifest["items"]["T_BIN"]
        assert item["output_kind"] == "bytes"
        assert (tmp_path / "s1" / "workspace" / "T_BIN.bin").read_bytes() == b"<html></html>"

    def test_load_roundtrips_dataframe(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        df = pd.DataFrame({"x": list(range(100))})
        ws.persist(make_task("T001"), make_output(df, status="done"), 0)

        loaded = ws.load("T001")
        assert loaded.output_type == "dataframe"
        assert isinstance(loaded.data, pd.DataFrame)
        assert len(loaded.data) == 100
        assert loaded.metadata.get("loaded_from_workspace") is True

    def test_load_roundtrips_str_and_json(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T_STR"), make_output("hello", status="done"), 0)
        ws.persist(make_task("T_JSON"), make_output({"a": 1, "b": [2, 3]}, status="done"), 0)

        s = ws.load("T_STR")
        assert s.data == "hello"
        assert s.output_type == "text"

        j = ws.load("T_JSON")
        assert j.data == {"a": 1, "b": [2, 3]}
        assert j.output_type == "json"

    def test_failed_task_recorded_but_not_persisted(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        task = make_task("T_FAIL", type="data_fetch")
        ws.persist(task, make_output(None, status="failed", error="endpoint timeout"), 0)

        assert "T_FAIL" in ws.manifest["items"]
        item = ws.manifest["items"]["T_FAIL"]
        assert item["status"] == "failed"
        assert item["path"] is None
        assert "endpoint timeout" in (item.get("error") or "")
        assert not (tmp_path / "s1" / "workspace" / "T_FAIL.parquet").exists()
        assert not (tmp_path / "s1" / "workspace" / "T_FAIL.json").exists()

    def test_unserializable_data_marks_status_and_raises(self, tmp_path):
        """parquet/feather/json 都失败 → status=unserializable AND raise.

        Spec §11 R8: "task 整体翻为 failed 状态 — execution 抛
        TaskError"; the workspace layer raises
        WorkspaceSerializationError, callers re-raise as TaskError. We
        also assert the manifest entry persists for audit visibility.
        """
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        task = make_task("T_BAD", type="data_fetch")
        bad: dict[str, Any] = {}
        bad["self"] = bad  # circular reference — json.dumps will raise

        with pytest.raises(WorkspaceSerializationError):
            ws.persist(task, make_output(bad, status="done"), 0)

        # Re-open to verify the manifest hit disk too (lock context
        # manager always flushes, even on exception).
        ws2 = SessionWorkspace(session_id="s1", root=tmp_path)
        item = ws2.manifest["items"]["T_BAD"]
        assert item["status"] == "unserializable"
        assert item["path"] is None

    def test_unsupported_data_type_raises(self, tmp_path):
        """Random python objects with no JSON / DataFrame mapping fail
        fast — no pickle fallback (security)."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)

        class _Custom:
            pass

        with pytest.raises(WorkspaceSerializationError):
            ws.persist(make_task("T_X"), make_output(_Custom(), status="done"), 0)

    def test_no_implicit_confirmed_propagation(self, tmp_path):
        """V6 取消隐式传播 — report_gen 完成不会自动标 上游 confirmed."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T001", type="data_fetch"),
                   make_output(pd.DataFrame({"x": [1]}), status="done"), 0)
        ws.persist(make_task("T002", type="analysis", depends_on=["T001"]),
                   make_output("...", status="done"), 0)
        ws.persist(make_task("R0_REPORT", type="report_gen", depends_on=["T002"]),
                   make_output(b"<html>", status="done"), 0)

        for tid in ("T001", "T002", "R0_REPORT"):
            assert ws.manifest["items"][tid]["user_confirmed"] is False
            assert ws.manifest["items"][tid]["confirmed_history"] == []

    def test_explicit_confirm_persists_to_history(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T001"),
                   make_output(pd.DataFrame({"x": [1]}), status="done"), 0)

        ws.mark_confirmed("T001", source="user_marked", actor="alice")
        item = ws.manifest["items"]["T001"]
        assert item["user_confirmed"] is True
        assert len(item["confirmed_history"]) == 1
        assert item["confirmed_history"][0]["action"] == "confirm"
        assert item["confirmed_history"][0]["actor"] == "alice"
        assert item["confirmed_history"][0]["source"] == "user_marked"

        ws.mark_unconfirmed("T001", actor="alice")
        item = ws.manifest["items"]["T001"]
        assert item["user_confirmed"] is False
        assert len(item["confirmed_history"]) == 2
        assert item["confirmed_history"][1]["action"] == "unconfirm"

    def test_confirm_unknown_task_raises(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        with pytest.raises(WorkspaceError):
            ws.mark_confirmed("GHOST")

    def test_load_missing_file_raises(self, tmp_path):
        """落盘后文件被外部删除，再 load 应明确报错."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T001"),
                   make_output(pd.DataFrame({"x": [1]}), status="done"), 0)
        (tmp_path / "s1" / "workspace" / "T001.parquet").unlink()

        with pytest.raises(WorkspaceError, match="missing|not found"):
            ws.load("T001")

    def test_load_unknown_task_raises(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        with pytest.raises(WorkspaceError, match="not found|GHOST"):
            ws.load("GHOST")

    def test_load_failed_task_raises(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T_FAIL"),
                   make_output(None, status="failed", error="x"), 0)
        with pytest.raises(WorkspaceError, match="cannot load"):
            ws.load("T_FAIL")

    def test_manifest_status_marked_missing_on_reload(self, tmp_path):
        """重新加载 workspace 时校验 path 存在性，缺失文件标 status=missing."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T001"),
                   make_output(pd.DataFrame({"x": [1]}), status="done"), 0)
        (tmp_path / "s1" / "workspace" / "T001.parquet").unlink()

        ws_reloaded = SessionWorkspace(session_id="s1", root=tmp_path)
        ws_reloaded.validate_paths()
        assert ws_reloaded.manifest["items"]["T001"]["status"] == "missing"

    def test_manifest_persists_across_instances(self, tmp_path):
        """A second SessionWorkspace for the same session reads the
        existing manifest (no implicit truncation)."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T001"),
                   make_output(pd.DataFrame({"x": [1]}), status="done"), 0)
        ws.mark_confirmed("T001", actor="bob")

        ws2 = SessionWorkspace(session_id="s1", root=tmp_path)
        assert "T001" in ws2.manifest["items"]
        assert ws2.manifest["items"]["T001"]["user_confirmed"] is True
        # And we can still load through the second instance.
        loaded = ws2.load("T001")
        assert isinstance(loaded.data, pd.DataFrame)

    def test_turn_status_lifecycle(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T001"),
                   make_output(pd.DataFrame({"x": [1]}), status="done"), turn_index=0)
        assert ws.manifest["items"]["T001"]["turn_status"] == "ongoing"

        ws.finalize_turn(turn_index=0)
        assert ws.manifest["items"]["T001"]["turn_status"] == "finalized"

        ws.persist(make_task("R1_T001"),
                   make_output(pd.DataFrame({"x": [2]}), status="done"), turn_index=1)
        ws.abandon_orphaned_turn(turn_index=1)
        assert ws.manifest["items"]["R1_T001"]["turn_status"] == "abandoned"
        # Finalized entries from prior turns must not be touched.
        assert ws.manifest["items"]["T001"]["turn_status"] == "finalized"

    def test_finalize_only_affects_target_turn(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("A"), make_output(pd.DataFrame({"x": [1]}), status="done"), 0)
        ws.persist(make_task("B"), make_output(pd.DataFrame({"x": [2]}), status="done"), 1)
        ws.finalize_turn(0)
        assert ws.manifest["items"]["A"]["turn_status"] == "finalized"
        assert ws.manifest["items"]["B"]["turn_status"] == "ongoing"

    def test_failed_task_visible_in_prompt_summary(self, tmp_path):
        """失败 / unserializable / missing 条目必须出现在 prompt 摘要中."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T_OK"),
                   make_output(pd.DataFrame({"x": [1]}), status="done"), 0)
        ws.persist(make_task("T_FAIL", type="data_fetch"),
                   make_output(None, status="failed", error="endpoint timeout"), 0)

        bad: dict[str, Any] = {}
        bad["self"] = bad
        with pytest.raises(WorkspaceSerializationError):
            ws.persist(make_task("T_BAD"), make_output(bad, status="done"), 0)

        summary = ws.render_prompt_summary()
        assert "T_OK" in summary
        assert "T_FAIL" in summary and "失败" in summary
        assert "endpoint timeout" in summary
        assert "T_BAD" in summary
        assert ("unserializable" in summary or "无法序列化" in summary)

    def test_prompt_summary_empty_workspace(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        summary = ws.render_prompt_summary()
        assert "暂无" in summary

    def test_dtype_normalisation_handles_object_columns(self, tmp_path):
        """Mixed-dtype object columns should be coerced and persisted as
        parquet (not feather) — tests the §5.2.1 standardisation step."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        df = pd.DataFrame({
            "mixed": [1, "two", 3.0, None],
            "name": ["a", "b", "c", "d"],
        })
        ws.persist(make_task("T_MIX"), make_output(df, status="done"), 0)
        item = ws.manifest["items"]["T_MIX"]
        assert item["status"] == "done"
        assert item["output_kind"] == "dataframe"
        # Reload should give us a DataFrame with the row count preserved.
        loaded = ws.load("T_MIX")
        assert len(loaded.data) == 4

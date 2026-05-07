"""SessionWorkspace — durable storage for task outputs (V6 §5.2).

Each session owns a directory ``{WORKSPACE_ROOT}/{session_id}/workspace/``
containing one file per persisted task plus a ``manifest.json`` index.
Cross-turn data reuse goes through the manifest: planning-layer LLM sees
a manifest summary, declares ``data_ref="T001"`` in the plan, and the
executor loads ``T001`` from the workspace before running the task.

Design constraints (from spec):
  * **No pickle.** Pickle reads execute arbitrary code; even single-session
    files can be tainted via backups / volume mounts.
  * **Failure must surface.** Any "task=done but artifact悄悄不可用" path
    is forbidden — serialization failure flips the task to ``failed`` and
    the manifest entry stays visible (status=unserializable / missing) so
    the planning LLM cannot pretend the task never existed.
  * **No implicit confirmation.** ``user_confirmed`` only flips on explicit
    user action via ``mark_confirmed`` (called by the workspace API in S6).
"""
from __future__ import annotations

import fcntl
import io
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

import pandas as pd

from backend.exceptions import WorkspaceError, WorkspaceSerializationError


logger = logging.getLogger("analytica.workspace")


# Fields below are descriptive — manifest items are plain dicts so they
# round-trip through json without any pydantic conversion overhead.
_PREVIEW_CHARS = 200
_SAMPLE_ROWS = 3


class SessionWorkspace:
    """Per-session workspace backed by a directory + manifest.json.

    The workspace is **idempotent on construction**: instantiating a
    second time with the same ``(session_id, root)`` reads the existing
    manifest from disk so all readers see the same state. Writes are
    serialized via fcntl.flock on the manifest file.
    """

    def __init__(self, session_id: str, root: str | os.PathLike[str]) -> None:
        self.session_id = session_id
        self.root = Path(root)
        self.workspace_dir = self.root / session_id / "workspace"
        self._manifest_path = self.workspace_dir / "manifest.json"
        # Load existing manifest if present; else empty.
        self.manifest: dict[str, Any] = self._load_manifest_from_disk()

    # ── manifest IO ────────────────────────────────────────────

    def _empty_manifest(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "items": {}}

    def _load_manifest_from_disk(self) -> dict[str, Any]:
        if not self._manifest_path.exists():
            return self._empty_manifest()
        try:
            raw = self._manifest_path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else self._empty_manifest()
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "manifest %s unreadable (%s); starting fresh",
                self._manifest_path, e,
            )
            return self._empty_manifest()
        # Preserve session_id from constructor — manifest may have been
        # copied from a different session by mistake.
        data.setdefault("session_id", self.session_id)
        data.setdefault("items", {})
        return data

    def _write_manifest_unsafe(self) -> None:
        """Write manifest to disk WITHOUT acquiring the lock. Callers
        must hold the lock via _locked_manifest()."""
        self._manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False, default=str, indent=2),
            encoding="utf-8",
        )

    @contextmanager
    def _locked_manifest(self) -> Iterator[None]:
        """Acquire an exclusive lock on the manifest file for the
        duration of the block. Reloads from disk before yielding so
        concurrent processes don't clobber each other's changes."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        # Open in r+ if exists, else create empty file.
        if not self._manifest_path.exists():
            self._manifest_path.write_text(
                json.dumps(self._empty_manifest(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        with self._manifest_path.open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.seek(0)
                raw = fh.read()
                try:
                    self.manifest = json.loads(raw) if raw.strip() else self._empty_manifest()
                except json.JSONDecodeError:
                    self.manifest = self._empty_manifest()
                self.manifest.setdefault("session_id", self.session_id)
                self.manifest.setdefault("items", {})
                try:
                    yield
                finally:
                    # Always flush — even if the caller raised. Failure
                    # paths still need to leave a manifest entry behind
                    # (e.g. status=unserializable) for audit visibility.
                    fh.seek(0)
                    fh.truncate()
                    fh.write(json.dumps(self.manifest, ensure_ascii=False, default=str, indent=2))
                    fh.flush()
                    try:
                        os.fsync(fh.fileno())
                    except OSError:
                        pass
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    # ── persistence ────────────────────────────────────────────

    _SUCCESS_STATUSES = frozenset({"success", "done", "partial"})
    _FAILURE_STATUSES = frozenset({"failed", "error"})
    _SKIPPED_STATUSES = frozenset({"skipped"})

    def persist(self, task: Any, output: Any, turn_index: int) -> None:
        """Persist a completed task to disk + manifest atomically.

        ``task`` is a TaskItem (or any object exposing task_id / type /
        tool / params / depends_on / name attributes). ``output`` is a
        ToolOutput (or any object exposing data / status / error_message
        attributes).

        Status mapping (consistent with backend.tools.base.ToolOutput):
          * ``success`` / ``done`` / ``partial`` → write file, manifest
            ``status="done"``
          * ``failed`` / ``error`` → record entry only, manifest
            ``status="failed"``
          * ``skipped`` → record entry only, manifest ``status="skipped"``
          * unknown values are coerced to ``failed`` for safety

        Failure semantics (V6 §11 R8 / "失败显式化"):
          * a serialization-time failure marks the entry
            ``unserializable`` AND raises
            ``WorkspaceSerializationError`` so the executor can flip the
            task itself to ``failed``.
        """
        task_id = self._task_attr(task, "task_id")
        if not task_id:
            raise WorkspaceError("task is missing task_id; cannot persist")

        with self._locked_manifest():
            base_entry = self._build_base_entry(task, turn_index)
            status = (self._output_attr(output, "status") or "").lower()

            if status in self._FAILURE_STATUSES:
                self._record_failed(base_entry, output, manifest_status="failed")
                self.manifest["items"][task_id] = base_entry
                return
            if status in self._SKIPPED_STATUSES:
                self._record_failed(base_entry, output, manifest_status="skipped")
                self.manifest["items"][task_id] = base_entry
                return
            if status not in self._SUCCESS_STATUSES:
                # Unknown status — surface as failed for audit, but do
                # NOT raise (caller's status is canonical for run-time
                # decisions; we just preserve the manifest trail).
                self._record_failed(base_entry, output, manifest_status="failed")
                self.manifest["items"][task_id] = base_entry
                return

            data = self._output_attr(output, "data")
            try:
                rel_path, output_kind, file_meta = self._serialize_to_disk(task_id, data)
            except WorkspaceSerializationError as e:
                base_entry.update(
                    status="unserializable",
                    path=None,
                    output_kind=self._infer_output_kind(data),
                    error=str(e),
                )
                self.manifest["items"][task_id] = base_entry
                # write_back happens via context manager; raise AFTER the
                # entry is staged so callers can flip task state knowing
                # the manifest is consistent.
                raise

            base_entry.update(
                status="done",
                path=rel_path,
                output_kind=output_kind,
                **file_meta,
            )
            self.manifest["items"][task_id] = base_entry

    def record_failure(self, task: Any, output: Any, turn_index: int = 0) -> None:
        """Record a failure entry without writing artifacts. Equivalent
        to ``persist(...)`` when output.status indicates failure — kept
        as a named entry-point so hooks can be explicit about intent
        (V6 §5.3.2)."""
        self.persist(task, output, turn_index=turn_index)

    # ── failure / loading helpers ──────────────────────────────

    @staticmethod
    def _task_attr(task: Any, name: str, default: Any = None) -> Any:
        """Read attr from TaskItem-like or dict-like task representation."""
        if isinstance(task, dict):
            return task.get(name, default)
        return getattr(task, name, default)

    @staticmethod
    def _output_attr(output: Any, name: str, default: Any = None) -> Any:
        if isinstance(output, dict):
            return output.get(name, default)
        return getattr(output, name, default)

    def _build_base_entry(self, task: Any, turn_index: int) -> dict[str, Any]:
        params = self._task_attr(task, "params") or {}
        if not isinstance(params, dict):
            params = {}
        endpoint = (
            params.get("endpoint_id")
            or params.get("endpoint")
            or None
        )
        return {
            "task_id": self._task_attr(task, "task_id"),
            "turn_index": int(turn_index),
            "type": self._task_attr(task, "type", default=""),
            "tool": self._task_attr(task, "tool", default=""),
            "name": self._task_attr(task, "name", default="") or "",
            "endpoint": endpoint,
            "params": dict(params),
            "depends_on": list(self._task_attr(task, "depends_on", default=[]) or []),
            "output_kind": None,
            "path": None,
            "size_bytes": 0,
            "schema": None,
            "rows": None,
            "sample": None,
            "preview": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "user_confirmed": False,
            "confirmed_history": [],
            "tags": [],
            "status": "pending",
            "turn_status": "ongoing",
            "error": None,
        }

    @staticmethod
    def _record_failed(
        entry: dict[str, Any],
        output: Any,
        *,
        manifest_status: str = "failed",
    ) -> None:
        err = (
            SessionWorkspace._output_attr(output, "error_message")
            or SessionWorkspace._output_attr(output, "error")
            or ""
        )
        entry.update(
            status=manifest_status,
            path=None,
            output_kind=None,
            error=str(err),
        )

    @staticmethod
    def _infer_output_kind(data: Any) -> str:
        if isinstance(data, pd.DataFrame):
            return "dataframe"
        if isinstance(data, str):
            return "str"
        if isinstance(data, bytes):
            return "bytes"
        if isinstance(data, (dict, list)):
            return "json"
        return "json"

    def _serialize_to_disk(
        self, task_id: str, data: Any,
    ) -> tuple[str, str, dict[str, Any]]:
        """Pick a serializer based on data type; write to workspace_dir.

        Returns (relative_path, output_kind, file_meta). file_meta has the
        DataFrame-specific schema/sample/rows or str-specific preview that
        the manifest item exposes to LLM prompts.
        """
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        if isinstance(data, pd.DataFrame):
            return self._persist_dataframe(task_id, data)
        if isinstance(data, str):
            return self._persist_str(task_id, data)
        if isinstance(data, bytes):
            return self._persist_bytes(task_id, data)
        if isinstance(data, (dict, list)):
            return self._persist_json(task_id, data)
        raise WorkspaceSerializationError(
            f"unsupported data type {type(data).__name__} for task {task_id}",
            task_id=task_id,
        )

    def _persist_dataframe(
        self, task_id: str, df: pd.DataFrame,
    ) -> tuple[str, str, dict[str, Any]]:
        """parquet → dtype-normalized parquet → feather → fail."""
        # 1) raw parquet
        payload = self._try_parquet(df)
        ext = "parquet" if payload is not None else None
        if payload is None:
            # 2) dtype normalisation
            df_norm = df.copy()
            for col in df_norm.columns:
                if df_norm[col].dtype == object:
                    df_norm[col] = df_norm[col].astype(str)
            payload = self._try_parquet(df_norm)
            if payload is not None:
                ext = "parquet"
        if payload is None:
            # 3) feather
            payload = self._try_feather(df)
            if payload is not None:
                ext = "feather"
        if payload is None:
            raise WorkspaceSerializationError(
                f"DataFrame {task_id} cannot serialize as parquet or feather",
                task_id=task_id,
            )

        rel_path = f"{task_id}.{ext}"
        (self.workspace_dir / rel_path).write_bytes(payload)
        meta: dict[str, Any] = {
            "size_bytes": len(payload),
            "schema": {
                "columns": list(df.columns.astype(str)),
                "dtypes": {str(c): str(df[c].dtype) for c in df.columns},
            },
            "rows": int(len(df)),
            "sample": self._dataframe_sample(df),
        }
        return rel_path, "dataframe", meta

    @staticmethod
    def _try_parquet(df: pd.DataFrame) -> Optional[bytes]:
        try:
            buf = io.BytesIO()
            df.to_parquet(buf, engine="pyarrow")
            return buf.getvalue()
        except Exception as e:  # noqa: BLE001 — fallback chain documented
            logger.debug("parquet attempt failed: %s", e)
            return None

    @staticmethod
    def _try_feather(df: pd.DataFrame) -> Optional[bytes]:
        try:
            buf = io.BytesIO()
            df.to_feather(buf)
            return buf.getvalue()
        except Exception as e:  # noqa: BLE001
            logger.debug("feather attempt failed: %s", e)
            return None

    @staticmethod
    def _dataframe_sample(df: pd.DataFrame) -> list[dict[str, Any]]:
        head = df.head(_SAMPLE_ROWS)
        # default=str via json round-trip keeps datetimes / decimals
        # readable in the manifest.
        return json.loads(head.to_json(orient="records", date_format="iso"))

    def _persist_json(
        self, task_id: str, data: Any,
    ) -> tuple[str, str, dict[str, Any]]:
        try:
            payload = json.dumps(
                data, ensure_ascii=False, default=str,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as e:
            raise WorkspaceSerializationError(
                f"json serialization failed for {task_id}: {e}",
                task_id=task_id,
            ) from e
        rel_path = f"{task_id}.json"
        (self.workspace_dir / rel_path).write_bytes(payload)
        preview = self._json_preview(data)
        return rel_path, "json", {
            "size_bytes": len(payload),
            "preview": preview,
        }

    @staticmethod
    def _json_preview(data: Any) -> str:
        try:
            text = json.dumps(data, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            text = repr(data)
        return text[:_PREVIEW_CHARS]

    def _persist_str(
        self, task_id: str, data: str,
    ) -> tuple[str, str, dict[str, Any]]:
        rel_path = f"{task_id}.txt"
        payload = data.encode("utf-8")
        (self.workspace_dir / rel_path).write_bytes(payload)
        return rel_path, "str", {
            "size_bytes": len(payload),
            "preview": data[:_PREVIEW_CHARS],
        }

    def _persist_bytes(
        self, task_id: str, data: bytes,
    ) -> tuple[str, str, dict[str, Any]]:
        rel_path = f"{task_id}.bin"
        (self.workspace_dir / rel_path).write_bytes(data)
        return rel_path, "bytes", {
            "size_bytes": len(data),
        }

    # ── load ───────────────────────────────────────────────────

    def load(self, task_id: str) -> Any:
        """Reconstruct a ToolOutput-like object from the manifest entry.

        Returns a backend.tools.base.ToolOutput. Raises WorkspaceError if
        the entry is missing, the underlying file is gone, or the entry
        is not in a loadable state (failed / unserializable / missing /
        cleared).
        """
        item = self.manifest["items"].get(task_id)
        if item is None:
            raise WorkspaceError(
                f"task {task_id!r} not found in workspace manifest",
            )
        status = item.get("status")
        if status != "done":
            raise WorkspaceError(
                f"task {task_id!r} status={status!r}; cannot load",
            )
        rel_path = item.get("path")
        if not rel_path:
            raise WorkspaceError(
                f"task {task_id!r} has no path; cannot load",
            )
        full_path = self.workspace_dir / rel_path
        if not full_path.exists():
            with self._locked_manifest():
                if task_id in self.manifest["items"]:
                    self.manifest["items"][task_id]["status"] = "missing"
            raise WorkspaceError(
                f"task {task_id!r} file missing on disk: {full_path}",
            )

        kind = item.get("output_kind")
        data = self._deserialize(full_path, kind)
        return self._build_tool_output(item, data)

    @staticmethod
    def _deserialize(path: Path, kind: str | None) -> Any:
        if kind == "dataframe":
            if path.suffix == ".feather":
                return pd.read_feather(path)
            return pd.read_parquet(path, engine="pyarrow")
        if kind == "json":
            return json.loads(path.read_text(encoding="utf-8"))
        if kind == "str":
            return path.read_text(encoding="utf-8")
        if kind == "bytes":
            return path.read_bytes()
        raise WorkspaceError(f"unknown output_kind={kind!r} for {path}")

    @staticmethod
    def _build_tool_output(item: dict[str, Any], data: Any) -> Any:
        # Lazy import to avoid a circular dep with backend.tools.base.
        from backend.tools.base import ToolOutput

        kind_to_type = {
            "dataframe": "dataframe",
            "json": "json",
            "str": "text",
            "bytes": "file",
        }
        return ToolOutput(
            tool_id=item.get("tool") or "workspace.load",
            status="success",
            output_type=kind_to_type.get(item.get("output_kind") or "json", "json"),
            data=data,
            metadata={
                "loaded_from_workspace": True,
                "workspace_task_id": item.get("task_id"),
                "turn_index": item.get("turn_index"),
            },
        )

    # ── confirmation / turn lifecycle ──────────────────────────

    def mark_confirmed(
        self, task_id: str, *, source: str = "user_marked", actor: str | None = None,
    ) -> None:
        with self._locked_manifest():
            item = self.manifest["items"].get(task_id)
            if item is None:
                raise WorkspaceError(
                    f"cannot confirm unknown task_id {task_id!r}",
                )
            item["user_confirmed"] = True
            item.setdefault("confirmed_history", []).append({
                "action": "confirm",
                "source": source,
                "actor": actor,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def mark_unconfirmed(self, task_id: str, *, actor: str | None = None) -> None:
        with self._locked_manifest():
            item = self.manifest["items"].get(task_id)
            if item is None:
                raise WorkspaceError(
                    f"cannot unconfirm unknown task_id {task_id!r}",
                )
            item["user_confirmed"] = False
            item.setdefault("confirmed_history", []).append({
                "action": "unconfirm",
                "source": "user_marked",
                "actor": actor,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def confirmed_history(self, task_id: str) -> list[dict[str, Any]]:
        item = self.manifest["items"].get(task_id) or {}
        return list(item.get("confirmed_history") or [])

    def finalize_turn(self, turn_index: int) -> None:
        """Flip every ``ongoing`` entry on this turn to ``finalized``."""
        with self._locked_manifest():
            for item in self.manifest["items"].values():
                if (
                    item.get("turn_index") == turn_index
                    and item.get("turn_status") == "ongoing"
                ):
                    item["turn_status"] = "finalized"

    def abandon_orphaned_turn(self, turn_index: int) -> None:
        """Mark leftover ongoing entries from a turn that the user
        abandoned (e.g. clarification dropped, new topic started)."""
        with self._locked_manifest():
            for item in self.manifest["items"].values():
                if (
                    item.get("turn_index") == turn_index
                    and item.get("turn_status") == "ongoing"
                ):
                    item["turn_status"] = "abandoned"

    # ── audit / introspection ──────────────────────────────────

    def validate_paths(self) -> None:
        """Walk every done entry and flip ``status=missing`` if the
        underlying file is gone (V6 §11 R9). Idempotent."""
        with self._locked_manifest():
            for item in self.manifest["items"].values():
                if item.get("status") != "done":
                    continue
                rel_path = item.get("path")
                if not rel_path:
                    item["status"] = "missing"
                    continue
                full = self.workspace_dir / rel_path
                if not full.exists():
                    item["status"] = "missing"

    def render_prompt_summary(self, *, current_turn_index: int | None = None) -> str:
        """Human-readable manifest summary for inclusion in LLM prompts.

        Visibility rules (V6 §7.3):
          * ``finalized`` + ``done`` → reusable
          * ``ongoing`` + same turn + ``done`` → reusable (in-flight upstream)
          * ``failed`` / ``unserializable`` / ``missing`` → render with
            explicit failure marker (never silently filtered)
          * ``abandoned`` and cross-turn ``ongoing`` → not rendered
        """
        items = self.manifest.get("items") or {}
        if not items:
            return "（workspace 暂无任何条目）"

        reusable: list[str] = []
        failed: list[str] = []

        for tid, item in items.items():
            status = item.get("status")
            turn_status = item.get("turn_status")
            if status == "done":
                if turn_status == "finalized":
                    reusable.append(self._format_reusable(tid, item))
                elif turn_status == "ongoing" and item.get("turn_index") == current_turn_index:
                    reusable.append(self._format_reusable(tid, item))
                elif turn_status == "ongoing" and current_turn_index is None:
                    # Default summary — render ongoing as reusable so audit
                    # views see it; explicit current_turn_index gates this.
                    reusable.append(self._format_reusable(tid, item))
                # cross-turn ongoing or abandoned: skip silently per spec
                continue
            if status in {"failed", "unserializable", "missing"}:
                failed.append(self._format_failed(tid, item, status))

        lines = ["【工作区已有产物】"]
        if reusable:
            lines.extend(reusable)
        else:
            lines.append("（暂无可复用产物）")
        if failed:
            lines.append("【失败/缺失条目】")
            lines.extend(failed)
        return "\n".join(lines)

    @staticmethod
    def _format_reusable(task_id: str, item: dict[str, Any]) -> str:
        kind = item.get("output_kind") or "?"
        confirmed = "✓" if item.get("user_confirmed") else " "
        meta_bits: list[str] = [f"kind={kind}"]
        if kind == "dataframe":
            schema = item.get("schema") or {}
            cols = schema.get("columns") or []
            meta_bits.append(f"rows={item.get('rows')}")
            meta_bits.append(f"cols={','.join(cols[:6])}")
        elif kind in {"str", "json"}:
            preview = item.get("preview") or ""
            if preview:
                preview_short = preview.replace("\n", " ")[:80]
                meta_bits.append(f"preview={preview_short!r}")
        return f"  [{confirmed}] {task_id} ({item.get('type','?')}/{item.get('tool','?')}) — {', '.join(meta_bits)}"

    @staticmethod
    def _format_failed(task_id: str, item: dict[str, Any], status: str) -> str:
        label = {
            "failed": "失败",
            "unserializable": "无法序列化(unserializable)",
            "missing": "已淘汰: 文件清理(missing)",
        }.get(status, status)
        err = item.get("error") or ""
        err_short = (str(err).replace("\n", " "))[:80]
        return f"  [失败: {label}] {task_id} ({item.get('type','?')}) — {err_short}"

    # ── miscellanea ────────────────────────────────────────────

    def has(self, task_id: str) -> bool:
        return task_id in self.manifest.get("items", {})

    def items(self) -> dict[str, Any]:
        return dict(self.manifest.get("items", {}))

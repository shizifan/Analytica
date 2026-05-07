"""Phase 5 — persist generated report files to disk + DB.

Report tools return file bytes / strings inline in ``ToolOutput.data``.
This module turns those into durable artifacts under ``REPORTS_DIR``,
writes a ``report_artifacts`` row, and returns the ID so downstream
payloads / REST endpoints can reference it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("analytica.artifact_store")


EXT_BY_FORMAT: dict[str, str] = {
    "html": "html",
    "docx": "docx",
    "pptx": "pptx",
    "markdown": "md",
    "md": "md",
    "file": "bin",
}


def _reports_dir() -> Path:
    """Resolve REPORTS_DIR relative to CWD unless already absolute."""
    from backend.config import get_settings

    raw = get_settings().REPORTS_DIR
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _safe_filename(title: str | None, fallback: str, ext: str) -> str:
    """Build a human-readable filename; strip path separators + colons."""
    base = (title or fallback or "report").strip()
    # Replace anything that's not a safe filename char.
    base = re.sub(r'[\\/:*?"<>|\s]+', "_", base)
    base = base.strip("._") or "report"
    return f"{base[:80]}.{ext}"


def _content_to_bytes(content: Any, fmt: str) -> bytes:
    """Normalise tool output data into bytes. Tools vary:
    - html / markdown → str
    - docx / pptx     → bytes (already binary)
    """
    if content is None:
        return b""
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    # Unknown shape — serialise as JSON so we at least capture something.
    try:
        return json.dumps(content, ensure_ascii=False, default=str).encode("utf-8")
    except Exception:
        return repr(content).encode("utf-8", errors="ignore")


async def persist_artifact(
    db: AsyncSession,
    *,
    session_id: str,
    task_id: str | None,
    tool_id: str | None,
    fmt: str,
    title: str | None,
    content: Any,
    meta: dict[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    """Write a file and create a report_artifacts row. Returns the row
    dict (with `id`) on success, or None if writing failed."""
    fmt_norm = (fmt or "file").lower()
    ext = EXT_BY_FORMAT.get(fmt_norm, "bin")
    artifact_id = uuid.uuid4().hex

    # Per-session directory keeps the filesystem scannable.
    reports_root = _reports_dir()
    session_dir = reports_root / session_id
    try:
        session_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.exception("report dir create failed: %s", session_dir)
        return None

    filename = _safe_filename(title, task_id or tool_id or artifact_id, ext)
    # Prefix with artifact id to avoid duplicate-name collisions across turns.
    fs_path = session_dir / f"{artifact_id[:8]}_{filename}"
    raw_bytes = _content_to_bytes(content, fmt_norm)

    try:
        fs_path.write_bytes(raw_bytes)
    except OSError:
        logger.exception("report file write failed: %s", fs_path)
        return None

    rel_path = str(fs_path.relative_to(reports_root))

    await db.execute(
        text(
            """
            INSERT INTO report_artifacts
                (id, session_id, task_id, tool_id, format, title,
                 file_path, size_bytes, status, meta)
            VALUES
                (:id, :sid, :tid, :tool, :fmt, :title,
                 :path, :size, 'ready', :meta)
            """
        ),
        {
            "id": artifact_id,
            "sid": session_id,
            "tid": task_id,
            "tool": tool_id,
            "fmt": fmt_norm,
            "title": (title or "")[:255] if title else None,
            "path": rel_path,
            "size": len(raw_bytes),
            "meta": json.dumps(meta or {}, ensure_ascii=False, default=str),
        },
    )
    await db.commit()

    return {
        "id": artifact_id,
        "session_id": session_id,
        "task_id": task_id,
        "tool_id": tool_id,
        "format": fmt_norm,
        "title": title,
        "file_path": rel_path,
        "size_bytes": len(raw_bytes),
        "status": "ready",
        "meta": meta or {},
    }


async def list_artifacts(
    db: AsyncSession, session_id: str,
) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT id, session_id, task_id, tool_id, format, title, "
            "file_path, size_bytes, status, meta, created_at "
            "FROM report_artifacts WHERE session_id = :sid "
            "ORDER BY created_at ASC"
        ),
        {"sid": session_id},
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        raw_meta = r[9]
        if isinstance(raw_meta, str):
            try:
                raw_meta = json.loads(raw_meta)
            except json.JSONDecodeError:
                raw_meta = {}
        out.append(
            {
                "id": r[0],
                "session_id": r[1],
                "task_id": r[2],
                "tool_id": r[3],
                "format": r[4],
                "title": r[5],
                "file_path": r[6],
                "size_bytes": int(r[7]) if r[7] is not None else None,
                "status": r[8],
                "meta": raw_meta,
                "created_at": r[10].isoformat() if isinstance(r[10], datetime) else r[10],
            }
        )
    return out


async def get_artifact(
    db: AsyncSession, artifact_id: str,
) -> Optional[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT id, session_id, task_id, tool_id, format, title, "
            "file_path, size_bytes, status, meta, created_at "
            "FROM report_artifacts WHERE id = :aid"
        ),
        {"aid": artifact_id},
    )
    row = rows.first()
    if row is None:
        return None
    raw_meta = row[9]
    if isinstance(raw_meta, str):
        try:
            raw_meta = json.loads(raw_meta)
        except json.JSONDecodeError:
            raw_meta = {}
    return {
        "id": row[0],
        "session_id": row[1],
        "task_id": row[2],
        "tool_id": row[3],
        "format": row[4],
        "title": row[5],
        "file_path": row[6],
        "size_bytes": int(row[7]) if row[7] is not None else None,
        "status": row[8],
        "meta": raw_meta,
        "created_at": row[10].isoformat() if isinstance(row[10], datetime) else row[10],
    }


def resolve_artifact_path(artifact: dict[str, Any]) -> Path:
    """Return the absolute filesystem path for an artifact row."""
    return _reports_dir() / artifact["file_path"]


def ensure_reports_dir() -> Path:
    """Create REPORTS_DIR if missing; returns its absolute path. Called
    from lifespan startup so misconfig surfaces early."""
    path = _reports_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


# V6 §5.6 — conversion-context pickle helpers (_context_dir,
# write_conversion_context, read_conversion_context) deleted.
#
# Re-rendering a report later (e.g. user clicks "生成 DOCX" after an
# HTML report) now flows through the workspace: the planner writes a
# new task whose params declare ``data_refs`` into manifest entries,
# and ``execution._resolve_data_refs`` hydrates those into the
# tool's execution_context. No pickle on disk → no RCE attack surface.

# Keep os import live for future use (relative path calculation etc.)
_ = os

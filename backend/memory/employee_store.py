"""Data access layer for Phase 4 employees + employee_versions tables.

Kept separate from `MemoryStore` (user prefs / slot history) so the
employee CRUD surface has its own home. Functions accept an AsyncSession
and commit before returning.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ── field list used by serialise/deserialise helpers ────────────
EMPLOYEE_COLUMNS = (
    "employee_id",
    "name",
    "description",
    "version",
    "initials",
    "status",
    "domains",
    "endpoints",
    "skills",
    "faqs",
    "perception",
    "planning",
    "created_at",
    "updated_at",
)


def _parse_json_field(raw: Any) -> Any:
    """DB drivers sometimes return JSON columns as strings."""
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = {
        "employee_id": row[0],
        "name": row[1],
        "description": row[2],
        "version": row[3],
        "initials": row[4],
        "status": row[5],
        "domains": _parse_json_field(row[6]),
        "endpoints": _parse_json_field(row[7]),
        "skills": _parse_json_field(row[8]),
        "faqs": _parse_json_field(row[9]),
        "perception": _parse_json_field(row[10]),
        "planning": _parse_json_field(row[11]),
        "created_at": row[12].isoformat() if isinstance(row[12], datetime) else row[12],
        "updated_at": row[13].isoformat() if isinstance(row[13], datetime) else row[13],
    }
    return d


async def list_employees(
    db: AsyncSession,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    where = "" if include_archived else "WHERE status != 'archived'"
    sql = (
        "SELECT employee_id, name, description, version, initials, status, "
        "domains, endpoints, skills, faqs, perception, planning, "
        "created_at, updated_at FROM employees "
        f"{where} ORDER BY name"
    )
    rows = await db.execute(text(sql))
    return [_row_to_dict(r) for r in rows]


async def get_employee(
    db: AsyncSession,
    employee_id: str,
) -> Optional[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT employee_id, name, description, version, initials, status, "
            "domains, endpoints, skills, faqs, perception, planning, "
            "created_at, updated_at FROM employees WHERE employee_id = :eid"
        ),
        {"eid": employee_id},
    )
    row = rows.first()
    if row is None:
        return None
    return _row_to_dict(row)


async def upsert_employee(
    db: AsyncSession,
    *,
    employee_id: str,
    name: str,
    description: str | None,
    version: str,
    initials: str | None,
    status: str,
    domains: list[str],
    endpoints: list[str],
    skills: list[str],
    faqs: list[dict[str, Any]],
    perception: dict[str, Any] | None,
    planning: dict[str, Any] | None,
) -> None:
    """Insert or update an employee by id. Used by both seed and POST/PUT."""
    params = {
        "eid": employee_id,
        "name": name,
        "description": description,
        "version": version,
        "initials": initials,
        "status": status,
        "domains": json.dumps(domains or [], ensure_ascii=False),
        "endpoints": json.dumps(endpoints or [], ensure_ascii=False),
        "skills": json.dumps(skills or [], ensure_ascii=False),
        "faqs": json.dumps(faqs or [], ensure_ascii=False),
        "perception": (
            json.dumps(perception, ensure_ascii=False) if perception is not None else None
        ),
        "planning": (
            json.dumps(planning, ensure_ascii=False) if planning is not None else None
        ),
    }
    await db.execute(
        text(
            """
            INSERT INTO employees
                (employee_id, name, description, version, initials, status,
                 domains, endpoints, skills, faqs, perception, planning)
            VALUES
                (:eid, :name, :description, :version, :initials, :status,
                 :domains, :endpoints, :skills, :faqs, :perception, :planning)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                description = VALUES(description),
                version = VALUES(version),
                initials = VALUES(initials),
                status = VALUES(status),
                domains = VALUES(domains),
                endpoints = VALUES(endpoints),
                skills = VALUES(skills),
                faqs = VALUES(faqs),
                perception = VALUES(perception),
                planning = VALUES(planning),
                updated_at = NOW()
            """
        ),
        params,
    )
    await db.commit()


async def delete_employee(db: AsyncSession, employee_id: str) -> bool:
    """Archive an employee — soft delete. Returns True if a row changed."""
    result = await db.execute(
        text(
            "UPDATE employees SET status = 'archived' "
            "WHERE employee_id = :eid AND status != 'archived'"
        ),
        {"eid": employee_id},
    )
    await db.commit()
    return bool(result.rowcount)


async def create_version_snapshot(
    db: AsyncSession,
    employee_id: str,
    version: str,
    snapshot: dict[str, Any],
    note: str | None = None,
) -> None:
    """Freeze the current profile as a version row (for audit/diff)."""
    await db.execute(
        text(
            """
            INSERT INTO employee_versions
                (employee_id, version, snapshot, note)
            VALUES
                (:eid, :ver, :snap, :note)
            ON DUPLICATE KEY UPDATE
                snapshot = VALUES(snapshot),
                note = VALUES(note)
            """
        ),
        {
            "eid": employee_id,
            "ver": version,
            "snap": json.dumps(snapshot, ensure_ascii=False),
            "note": note,
        },
    )
    await db.commit()


async def list_versions(
    db: AsyncSession, employee_id: str,
) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT version, note, created_at FROM employee_versions "
            "WHERE employee_id = :eid ORDER BY created_at DESC"
        ),
        {"eid": employee_id},
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "version": r[0],
                "note": r[1],
                "created_at": r[2].isoformat() if isinstance(r[2], datetime) else r[2],
            }
        )
    return out


async def get_version_snapshot(
    db: AsyncSession, employee_id: str, version: str,
) -> Optional[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT snapshot FROM employee_versions "
            "WHERE employee_id = :eid AND version = :ver"
        ),
        {"eid": employee_id, "ver": version},
    )
    row = rows.first()
    if row is None:
        return None
    return _parse_json_field(row[0])

"""Complete the skill→tool rename across schema and data.

Rationale: an earlier rename (commit 7021054) renamed Python classes from
`Skill*` to `Tool*` and ID prefixes from `skill_*` to `tool_*`, but the
follow-up migration 20260424_0001 only updated *values* (PK contents) in
three tables. Schema names (`skill_id` columns, `skill_notes` table, JSON
elements inside `employees.skills`) were never renamed.

This migration finishes the job:

  1. `tools.skill_id`              → `tools.tool_id`              (PK)
  2. `report_artifacts.skill_id`   → `report_artifacts.tool_id`
  3. `skill_notes` table           → `tool_notes`
     · column `skill_id`            → `tool_id`
     · constraint `uq_skill_user`   → `uq_tool_user`
  4. `employees.skills`            → `employees.tools`           (column rename)
     · JSON elements `"skill_*"`   → `"tool_*"`                   (value rewrite)

`agent_skills` is intentionally left untouched — that table backs SKILL.md
SOP records (the *real* skill concept), not tool registrations.

The value-level UPDATEs from 20260424_0001 are re-applied here as a no-op
safety net (REPLACE on a string already containing `tool_` does nothing),
so this migration leaves the DB in a consistent state regardless of
whether 20260424 was previously applied.

Revision ID: 20260425_0001
Revises: 20260424_0001
Create Date: 2026-04-25
"""
from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


revision: str = "20260425_0001"
down_revision: Union[str, None] = "20260424_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. Idempotent value rewrite (safety net for partial 20260424) ──
    conn.execute(text(
        "UPDATE tools SET skill_id = REPLACE(skill_id, 'skill_', 'tool_') "
        "WHERE skill_id LIKE 'skill_%'"
    ))
    conn.execute(text(
        "UPDATE report_artifacts SET skill_id = REPLACE(skill_id, 'skill_', 'tool_') "
        "WHERE skill_id LIKE 'skill_%'"
    ))
    conn.execute(text(
        "UPDATE skill_notes SET skill_id = REPLACE(skill_id, 'skill_', 'tool_') "
        "WHERE skill_id LIKE 'skill_%'"
    ))

    # ── 2. tools.skill_id → tools.tool_id (PK rename) ──
    op.alter_column(
        "tools", "skill_id",
        new_column_name="tool_id",
        existing_type=sa.String(length=100),
        existing_nullable=False,
    )

    # ── 3. report_artifacts.skill_id → report_artifacts.tool_id ──
    op.alter_column(
        "report_artifacts", "skill_id",
        new_column_name="tool_id",
        existing_type=sa.String(length=100),
        existing_nullable=True,
    )

    # ── 4. skill_notes → tool_notes (table + column + constraint) ──
    # Drop the unique constraint first so the column rename is unambiguous.
    op.drop_constraint("uq_skill_user", "skill_notes", type_="unique")
    op.alter_column(
        "skill_notes", "skill_id",
        new_column_name="tool_id",
        existing_type=sa.String(length=100),
        existing_nullable=False,
    )
    op.rename_table("skill_notes", "tool_notes")
    op.create_unique_constraint("uq_tool_user", "tool_notes", ["tool_id", "user_id"])

    # ── 5a. employees.skills JSON value rewrite (must precede column rename) ──
    # Each row's `skills` is a JSON array of strings like
    # ["skill_api_fetch", ...]. Pull, rewrite, push back.
    rows = conn.execute(
        text("SELECT employee_id, skills FROM employees")
    ).fetchall()
    for emp_id, raw in rows:
        if raw is None:
            continue
        skills = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(skills, list):
            continue
        renamed = [
            s.replace("skill_", "tool_", 1)
            if isinstance(s, str) and s.startswith("skill_")
            else s
            for s in skills
        ]
        if renamed != skills:
            conn.execute(
                text("UPDATE employees SET skills = :skills WHERE employee_id = :eid"),
                {"skills": json.dumps(renamed, ensure_ascii=False), "eid": emp_id},
            )

    # ── 5b. employees.skills → employees.tools (column rename) ──
    op.alter_column(
        "employees", "skills",
        new_column_name="tools",
        existing_type=sa.JSON(),
        existing_nullable=False,
    )

    # Snapshot rows in employee_versions also store `skills` inside the
    # `snapshot` JSON blob — rewrite the inner key for consistency.
    snap_rows = conn.execute(
        text("SELECT employee_id, version, snapshot FROM employee_versions")
    ).fetchall()
    for emp_id, ver, raw in snap_rows:
        if raw is None:
            continue
        snap = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(snap, dict) or "skills" not in snap:
            continue
        snap["tools"] = [
            s.replace("skill_", "tool_", 1)
            if isinstance(s, str) and s.startswith("skill_")
            else s
            for s in (snap.get("skills") or [])
        ]
        snap.pop("skills", None)
        conn.execute(
            text(
                "UPDATE employee_versions SET snapshot = :snap "
                "WHERE employee_id = :eid AND version = :ver"
            ),
            {"snap": json.dumps(snap, ensure_ascii=False), "eid": emp_id, "ver": ver},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse order of upgrade.

    # ── 5b. employees.tools → employees.skills (column rename revert) ──
    op.alter_column(
        "employees", "tools",
        new_column_name="skills",
        existing_type=sa.JSON(),
        existing_nullable=False,
    )

    # ── 5a. employees.skills JSON: tool_* → skill_* ──
    rows = conn.execute(
        text("SELECT employee_id, skills FROM employees")
    ).fetchall()
    for emp_id, raw in rows:
        if raw is None:
            continue
        skills = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(skills, list):
            continue
        reverted = [
            s.replace("tool_", "skill_", 1)
            if isinstance(s, str) and s.startswith("tool_")
            else s
            for s in skills
        ]
        if reverted != skills:
            conn.execute(
                text("UPDATE employees SET skills = :skills WHERE employee_id = :eid"),
                {"skills": json.dumps(reverted, ensure_ascii=False), "eid": emp_id},
            )

    # Revert employee_versions snapshot `tools` back to `skills`.
    snap_rows = conn.execute(
        text("SELECT employee_id, version, snapshot FROM employee_versions")
    ).fetchall()
    for emp_id, ver, raw in snap_rows:
        if raw is None:
            continue
        snap = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(snap, dict) or "tools" not in snap:
            continue
        snap["skills"] = [
            s.replace("tool_", "skill_", 1)
            if isinstance(s, str) and s.startswith("tool_")
            else s
            for s in (snap.get("tools") or [])
        ]
        snap.pop("tools", None)
        conn.execute(
            text(
                "UPDATE employee_versions SET snapshot = :snap "
                "WHERE employee_id = :eid AND version = :ver"
            ),
            {"snap": json.dumps(snap, ensure_ascii=False), "eid": emp_id, "ver": ver},
        )

    # ── 4. tool_notes → skill_notes ──
    op.drop_constraint("uq_tool_user", "tool_notes", type_="unique")
    op.rename_table("tool_notes", "skill_notes")
    op.alter_column(
        "skill_notes", "tool_id",
        new_column_name="skill_id",
        existing_type=sa.String(length=100),
        existing_nullable=False,
    )
    op.create_unique_constraint("uq_skill_user", "skill_notes", ["skill_id", "user_id"])

    # ── 3. report_artifacts ──
    op.alter_column(
        "report_artifacts", "tool_id",
        new_column_name="skill_id",
        existing_type=sa.String(length=100),
        existing_nullable=True,
    )

    # ── 2. tools ──
    op.alter_column(
        "tools", "tool_id",
        new_column_name="skill_id",
        existing_type=sa.String(length=100),
        existing_nullable=False,
    )

    # ── 1. Reverse value rewrite ──
    conn.execute(text(
        "UPDATE skill_notes SET skill_id = REPLACE(skill_id, 'tool_', 'skill_') "
        "WHERE skill_id LIKE 'tool_%'"
    ))
    conn.execute(text(
        "UPDATE report_artifacts SET skill_id = REPLACE(skill_id, 'tool_', 'skill_') "
        "WHERE skill_id LIKE 'tool_%'"
    ))
    conn.execute(text(
        "UPDATE skills SET skill_id = REPLACE(skill_id, 'tool_', 'skill_') "
        "WHERE skill_id LIKE 'tool_%'"
    ))

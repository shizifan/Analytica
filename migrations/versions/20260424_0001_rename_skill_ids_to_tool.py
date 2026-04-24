"""Rename tool IDs from skill_ prefix to tool_ prefix

Revision ID: 20260424_0001
Revises: 20260423_0001
Create Date: 2026-04-24
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "20260424_0001"
down_revision: Union[str, None] = "20260423_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # tools table: skill_id is the PK — update in place (MySQL allows PK update)
    conn.execute(text(
        "UPDATE tools SET skill_id = REPLACE(skill_id, 'skill_', 'tool_') "
        "WHERE skill_id LIKE 'skill_%'"
    ))
    # report_artifacts stores the originating skill_id
    conn.execute(text(
        "UPDATE report_artifacts SET skill_id = REPLACE(skill_id, 'skill_', 'tool_') "
        "WHERE skill_id LIKE 'skill_%'"
    ))
    # skill_notes stores per-tool feedback keyed by skill_id
    conn.execute(text(
        "UPDATE skill_notes SET skill_id = REPLACE(skill_id, 'skill_', 'tool_') "
        "WHERE skill_id LIKE 'skill_%'"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(
        "UPDATE tools SET skill_id = REPLACE(skill_id, 'tool_', 'skill_') "
        "WHERE skill_id LIKE 'tool_%'"
    ))
    conn.execute(text(
        "UPDATE report_artifacts SET skill_id = REPLACE(skill_id, 'tool_', 'skill_') "
        "WHERE skill_id LIKE 'tool_%'"
    ))
    conn.execute(text(
        "UPDATE skill_notes SET skill_id = REPLACE(skill_id, 'tool_', 'skill_') "
        "WHERE skill_id LIKE 'tool_%'"
    ))

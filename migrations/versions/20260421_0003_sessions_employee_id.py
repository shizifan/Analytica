"""sessions.employee_id column (no-op)

Revision ID: 20260421_0003
Revises: 20260421_0002
Create Date: 2026-04-21

This revision was created during Phase 4 to add `sessions.employee_id`,
but that column already exists from the initial `347e30f8de94` migration
(`VARCHAR(100)` with an auto-generated index). Re-adding it would abort
the upgrade with a "duplicate column name" error, so the body is now a
no-op. The revision number is preserved to keep the migration chain
linear across environments that already stamped it.
"""
from __future__ import annotations

from typing import Sequence, Union


revision: str = "20260421_0003"
down_revision: Union[str, None] = "20260421_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Column already present; nothing to do.
    pass


def downgrade() -> None:
    pass

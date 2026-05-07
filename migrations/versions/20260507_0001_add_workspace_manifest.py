"""add workspace_manifest_json column to sessions

Revision ID: 20260507_0001
Revises: 20260501_0001
Create Date: 2026-05-07

V6 §5.2.6 — sessions.workspace_manifest_json holds an optional snapshot
of the SessionWorkspace manifest. The on-disk manifest.json under
WORKSPACE_ROOT remains the source of truth; this column lets API
endpoints read manifest state without touching the filesystem.

Existing rows stay NULL (no historical backfill — V6 is a clean cut-over;
the loader treats NULL as an empty manifest).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260507_0001"
down_revision: Union[str, None] = "20260501_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("workspace_manifest_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "workspace_manifest_json")

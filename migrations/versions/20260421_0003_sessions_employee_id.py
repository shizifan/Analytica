"""sessions.employee_id column

Revision ID: 20260421_0003
Revises: 20260421_0002
Create Date: 2026-04-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260421_0003"
down_revision: Union[str, None] = "20260421_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("employee_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "idx_sessions_employee_id", "sessions", ["employee_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_sessions_employee_id", table_name="sessions")
    op.drop_column("sessions", "employee_id")

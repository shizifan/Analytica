"""report_artifacts

Revision ID: 20260421_0004
Revises: 20260421_0003
Create Date: 2026-04-21

Phase 5. Persist generated report files (DOCX / PPTX / HTML / MD) so the
frontend can download / preview them after the graph run has finished.
Rows reference a file on the shared REPORTS_DIR volume; the `status`
column distinguishes in-progress vs ready vs failed artifacts.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260421_0004"
down_revision: Union[str, None] = "20260421_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("skill_id", sa.String(length=100), nullable=True),
        sa.Column(
            "format",
            sa.String(length=16),
            nullable=False,
            comment="html / docx / pptx / markdown",
        ),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "file_path",
            sa.String(length=512),
            nullable=False,
            comment="Path relative to REPORTS_DIR",
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="ready",
            comment="ready / failed",
        ),
        sa.Column(
            "meta",
            sa.JSON(),
            nullable=True,
            comment="slide_count / mode / chart_count etc.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_report_artifacts_session",
        "report_artifacts",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_report_artifacts_session", table_name="report_artifacts")
    op.drop_table("report_artifacts")

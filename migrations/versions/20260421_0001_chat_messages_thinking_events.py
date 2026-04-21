"""chat_messages + thinking_events + sessions rail columns

Revision ID: 20260421_0001
Revises: 347e30f8de94
Create Date: 2026-04-21

Phase 2 of the UI revamp. Introduces dedicated tables for chat message
history and a per-session thinking/tool-call audit stream, plus rail
columns on `sessions` that drive the HistoryPane (title / pinned /
deleted_at). LangGraph checkpoint state continues to live in
`sessions.state_json`; the new tables are append-only projections used
for display and replay.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260421_0001"
down_revision: Union[str, None] = "347e30f8de94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── sessions: rail columns (HistoryPane) ──────────────────
    op.add_column(
        "sessions",
        sa.Column("title", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "pinned",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "sessions",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "idx_sessions_user_updated",
        "sessions",
        ["user_id", "updated_at"],
    )

    # ── chat_messages ────────────────────────────────────────
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            comment="user / assistant / system",
        ),
        sa.Column(
            "type",
            sa.String(length=32),
            nullable=False,
            server_default="text",
            comment="text / plan_confirm / exec / chart_result / report_result / reflection_card",
        ),
        sa.Column("phase", sa.String(length=32), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=True,
            comment="Structured data for non-text message types",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_chat_messages_session_id",
        "chat_messages",
        ["session_id", "id"],
    )

    # ── thinking_events ──────────────────────────────────────
    op.create_table(
        "thinking_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            comment="thinking / tool / decision / phase",
        ),
        sa.Column("phase", sa.String(length=32), nullable=True),
        sa.Column(
            "ts_ms",
            sa.BigInteger(),
            nullable=False,
            comment="monotonic millis since session start",
        ),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "idx_thinking_events_session_id",
        "thinking_events",
        ["session_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("idx_thinking_events_session_id", table_name="thinking_events")
    op.drop_table("thinking_events")

    op.drop_index("idx_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("idx_sessions_user_updated", table_name="sessions")
    op.drop_column("sessions", "deleted_at")
    op.drop_column("sessions", "pinned")
    op.drop_column("sessions", "title")

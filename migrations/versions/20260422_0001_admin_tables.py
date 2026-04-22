"""admin tables — api_endpoints + api_call_stats + skills + domains + audit_logs

Revision ID: 20260422_0001
Revises: 20260421_0004
Create Date: 2026-04-22

Phase 6 — promotes the API registry, skill registry, and business-domain
catalogue to MySQL so the admin console can CRUD them. Adds audit_logs
to capture mutations (middleware landing in Phase 7).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260422_0001"
down_revision: Union[str, None] = "20260421_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── api_endpoints ─────────────────────────────────────────
    op.create_table(
        "api_endpoints",
        sa.Column("name", sa.String(length=128), primary_key=True),
        sa.Column(
            "method",
            sa.String(length=8),
            nullable=False,
            server_default="GET",
        ),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("domain", sa.String(length=8), nullable=False),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("time_type", sa.String(length=32), nullable=True),
        sa.Column("granularity", sa.String(length=32), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("required_params", sa.JSON(), nullable=True),
        sa.Column("optional_params", sa.JSON(), nullable=True),
        sa.Column("returns", sa.Text(), nullable=True),
        sa.Column("param_note", sa.Text(), nullable=True),
        sa.Column("disambiguate", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=8),
            nullable=False,
            server_default="mock",
            comment="mock / prod",
        ),
        sa.Column(
            "enabled",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("idx_api_endpoints_domain", "api_endpoints", ["domain"])

    # ── api_call_stats (daily roll-ups) ──────────────────────
    op.create_table(
        "api_call_stats",
        sa.Column("api_name", sa.String(length=128), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("p50_ms", sa.Integer(), nullable=True),
        sa.Column("p95_ms", sa.Integer(), nullable=True),
        sa.Column("last_called_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("api_name", "day"),
    )

    # ── skills ────────────────────────────────────────────────
    op.create_table(
        "skills",
        sa.Column("skill_id", sa.String(length=100), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            comment="data_fetch / analysis / visualization / report / search",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("input_spec", sa.Text(), nullable=True),
        sa.Column("output_spec", sa.Text(), nullable=True),
        sa.Column("domains", sa.JSON(), nullable=True),
        sa.Column(
            "enabled",
            sa.SmallInteger(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_msg", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("idx_skills_kind", "skills", ["kind"])

    # ── domains ───────────────────────────────────────────────
    op.create_table(
        "domains",
        sa.Column("code", sa.String(length=8), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("top_tags", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # ── audit_logs ────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "ts",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column(
            "actor_type",
            sa.String(length=16),
            nullable=False,
            server_default="user",
            comment="user / agent / system",
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=True),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column(
            "result",
            sa.String(length=16),
            nullable=False,
            server_default="success",
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("diff", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "idx_audit_resource",
        "audit_logs",
        ["resource_type", "resource_id", "ts"],
    )
    op.create_index("idx_audit_ts", "audit_logs", ["ts"])


def downgrade() -> None:
    op.drop_index("idx_audit_ts", table_name="audit_logs")
    op.drop_index("idx_audit_resource", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("domains")
    op.drop_index("idx_skills_kind", table_name="skills")
    op.drop_table("skills")
    op.drop_table("api_call_stats")
    op.drop_index("idx_api_endpoints_domain", table_name="api_endpoints")
    op.drop_table("api_endpoints")

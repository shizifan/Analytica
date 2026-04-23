"""tools table (rename from skills) + agent_skills table

Phase 7 — renames the skills table to tools (Python tool classes are "tools",
not "skills" in the Anthropic taxonomy) and adds the agent_skills table for
SKILL.md workflow instructions uploaded by users.

Revision ID: 20260423_0001
Revises: 20260422_0001
Create Date: 2026-04-23
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260423_0001"
down_revision: Union[str, None] = "20260422_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename skills → tools; existing rows are preserved.
    op.rename_table("skills", "tools")
    # Recreate the kind index under the canonical new name.
    op.create_index("idx_tools_kind", "tools", ["kind"])
    op.drop_index("idx_skills_kind", table_name="tools")

    # agent_skills — stores SKILL.md workflow instructions uploaded by users.
    op.create_table(
        "agent_skills",
        sa.Column("skill_id", sa.String(length=100), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
            comment="Full SKILL.md content including YAML frontmatter",
        ),
        sa.Column("author", sa.String(length=128), nullable=True),
        sa.Column("version", sa.String(length=32), nullable=True, server_default="1.0"),
        sa.Column("tags", sa.JSON(), nullable=True),
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
    op.create_index("idx_agent_skills_enabled", "agent_skills", ["enabled"])


def downgrade() -> None:
    op.drop_index("idx_agent_skills_enabled", table_name="agent_skills")
    op.drop_table("agent_skills")
    op.create_index("idx_skills_kind", "tools", ["kind"])
    op.drop_index("idx_tools_kind", table_name="tools")
    op.rename_table("tools", "skills")

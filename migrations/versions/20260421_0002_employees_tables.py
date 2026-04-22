"""employees + employee_versions tables

Revision ID: 20260421_0002
Revises: 20260421_0001
Create Date: 2026-04-21

Phase 4 of the UI revamp. Promotes employee profiles from YAML files to
a DB table so they can be created/edited/versioned via admin UI. The
YAML files stay in repo as seed source; runtime reads from DB when
``FF_EMPLOYEE_SOURCE=db`` and falls back to YAML otherwise.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260421_0002"
down_revision: Union[str, None] = "20260421_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("employee_id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "version",
            sa.String(length=32),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column("initials", sa.String(length=8), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
            comment="active / draft / archived",
        ),
        sa.Column(
            "domains",
            sa.JSON(),
            nullable=False,
            comment="list[str] of domain codes e.g. ['D1','D2']",
        ),
        sa.Column(
            "endpoints",
            sa.JSON(),
            nullable=False,
            comment="list[str] of endpoint ids; [] = auto-derive from domains",
        ),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column(
            "faqs",
            sa.JSON(),
            nullable=False,
            comment="list[{id, question, tag?, type?}] for EmptyHero FAQ grid",
        ),
        sa.Column(
            "perception",
            sa.JSON(),
            nullable=True,
            comment="{domain_keywords, extra_slots, slot_constraints, system_prompt_suffix}",
        ),
        sa.Column(
            "planning",
            sa.JSON(),
            nullable=True,
            comment="{prompt_suffix}",
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
    op.create_index("idx_employees_status", "employees", ["status"])

    op.create_table(
        "employee_versions",
        sa.Column("employee_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column(
            "snapshot",
            sa.JSON(),
            nullable=False,
            comment="Full profile snapshot at this version",
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("employee_id", "version"),
    )


def downgrade() -> None:
    op.drop_table("employee_versions")
    op.drop_index("idx_employees_status", table_name="employees")
    op.drop_table("employees")

"""api_endpoints — add semantic-enrichment columns

P2.4-1 of the API-registry → DB migration. The original ``api_endpoints``
schema (20260422_0001) covered the structural fields only. The four
columns below (``field_schema`` / ``use_cases`` / ``chain_with`` /
``analysis_note``) carry the planning-prompt semantics that ``ApiEndpoint``
already exposes in code; without them, switching ``FF_API_REGISTRY_SOURCE``
to ``db`` would silently degrade planner quality.

JSON columns chosen for the three list-shaped fields (decision Q1: keep
the structure queryable per row, no JSON parsing on the DB side); the
free-form ``analysis_note`` stays plain text.

Revision ID: 20260429_0001
Revises: 20260425_0001
Create Date: 2026-04-29
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260429_0001"
down_revision: Union[str, None] = "20260425_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # field_schema — list of (name, type, desc[, label_zh]) rows
    op.add_column(
        "api_endpoints",
        sa.Column("field_schema", sa.JSON(), nullable=True),
    )
    # use_cases — list of typical analyst questions
    op.add_column(
        "api_endpoints",
        sa.Column("use_cases", sa.JSON(), nullable=True),
    )
    # chain_with — list of recommended companion endpoints
    op.add_column(
        "api_endpoints",
        sa.Column("chain_with", sa.JSON(), nullable=True),
    )
    # analysis_note — free-form caveat / data-shape note
    op.add_column(
        "api_endpoints",
        sa.Column("analysis_note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("api_endpoints", "analysis_note")
    op.drop_column("api_endpoints", "chain_with")
    op.drop_column("api_endpoints", "use_cases")
    op.drop_column("api_endpoints", "field_schema")

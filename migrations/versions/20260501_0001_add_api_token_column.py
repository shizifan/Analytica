"""add api_token column to api_endpoints

Revision ID: 20260501_0001
Revises: 20260429_0001
Create Date: 2026-05-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260501_0001"
down_revision: Union[str, None] = "20260429_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_endpoints",
        sa.Column("api_token", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("api_endpoints", "api_token")

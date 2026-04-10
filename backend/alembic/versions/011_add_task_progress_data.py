"""Add progress_data JSONB column to tasks

Revision ID: 011
Revises: 010
Create Date: 2026-04-10 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS progress_data JSONB")


def downgrade() -> None:
    op.drop_column("tasks", "progress_data")

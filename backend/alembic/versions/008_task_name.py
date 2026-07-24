"""Add name column to tasks

Revision ID: 008
Revises: 007
Create Date: 2026-04-02 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS name VARCHAR(200)")


def downgrade() -> None:
    op.drop_column("tasks", "name")

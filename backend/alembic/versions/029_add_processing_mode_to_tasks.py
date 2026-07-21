"""Добавить колонку processing_mode в tasks (режим обработки ESTIMATE_FROM_LIST: fast/batch)

Revision ID: 029
Revises: 028
Create Date: 2026-07-21 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tasks "
        "ADD COLUMN IF NOT EXISTS processing_mode VARCHAR(10) NOT NULL DEFAULT 'fast'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS processing_mode")

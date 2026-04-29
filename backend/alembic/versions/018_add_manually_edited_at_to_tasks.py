"""Добавить поле manually_edited_at в tasks для отслеживания ручного редактирования

Revision ID: 018
Revises: 017
Create Date: 2026-04-30 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE tasks
        ADD COLUMN IF NOT EXISTS manually_edited_at TIMESTAMPTZ NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS manually_edited_at")

"""Добавить поле deleted_at для мягкого удаления задач (корзина)

Revision ID: 016
Revises: 015
Create Date: 2026-04-24 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE tasks
        ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tasks_deleted_at ON tasks (deleted_at)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tasks_deleted_at")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS deleted_at")

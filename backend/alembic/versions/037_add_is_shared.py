"""Общий признак is_shared для projects/tasks (старые данные компании — видны всем)

Revision ID: 037
Revises: 036
Create Date: 2026-07-28 00:00:00.000000

is_shared=true → ресурс виден всем сотрудникам (поверх изоляции по владельцу).
Используется для старых данных компании: backfill в main.py помечает их
owner=admin + is_archived=true + is_shared=true. Идемпотентно.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "037"
down_revision: Union[str, None] = "036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_projects_is_shared ON projects (is_shared)")
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_shared BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_is_shared ON tasks (is_shared)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tasks_is_shared")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS is_shared")
    op.execute("DROP INDEX IF EXISTS ix_projects_is_shared")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS is_shared")

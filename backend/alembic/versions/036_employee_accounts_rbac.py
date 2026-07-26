"""RBAC сотрудников: роли, владелец проекта, архив, поля аккаунта

Revision ID: 036
Revises: 035
Create Date: 2026-07-27 00:00:00.000000

Расширяет модель под персональные аккаунты и матрицу прав:
- users.role / tasks.user_role → VARCHAR(32) (влезают 'project_manager', 'head_of_sales');
- users.full_name, users.is_active (деактивация вместо удаления);
- projects.owner_id (FK users, ON DELETE SET NULL) + индекс;
- projects.is_archived, tasks.is_archived (+ индексы) — раздел «Архив».

Данные (backfill владельца-админа на legacy-строки) переносятся в рантайме
в main.py::_initialize_users, т.к. id админа известен только после сидинга.
Все операции идемпотентны (IF NOT EXISTS / ALTER TYPE).
"""
from typing import Sequence, Union
from alembic import op

revision: str = "036"
down_revision: Union[str, None] = "035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Роли: расширяем под длинные значения ('project_manager' = 14 символов).
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(32)")
    op.execute("ALTER TABLE tasks ALTER COLUMN user_role TYPE VARCHAR(32)")

    # Поля аккаунта.
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(100)")
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true"
    )

    # Владелец проекта.
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_id INTEGER "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id)"
    )

    # Архив: ортогональный флаг для проектов и задач.
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_projects_is_archived ON projects (is_archived)"
    )
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_is_archived ON tasks (is_archived)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tasks_is_archived")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS is_archived")
    op.execute("DROP INDEX IF EXISTS ix_projects_is_archived")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS is_archived")
    op.execute("DROP INDEX IF EXISTS ix_projects_owner_id")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS owner_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_active")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS full_name")
    op.execute("ALTER TABLE tasks ALTER COLUMN user_role TYPE VARCHAR(10)")
    op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(10)")

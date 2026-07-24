"""Личные аккаунты: users.username + tasks.owner_id (для мультиюзера и fairness)

Revision ID: 032
Revises: 031
Create Date: 2026-07-24 00:00:00.000000

Оба поля nullable — обратная совместимость: legacy-роли user/admin (общие пароли)
без username, legacy-задачи без owner_id продолжают работать.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "032"
down_revision: Union[str, None] = "031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(50)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)"
    )
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_id INTEGER "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_owner_id ON tasks (owner_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tasks_owner_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS owner_id")
    op.execute("DROP INDEX IF EXISTS ix_users_username")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS username")

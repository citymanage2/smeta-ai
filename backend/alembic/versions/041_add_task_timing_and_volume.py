"""Факты для прогноза времени: когда задача реально считалась и какого она объёма

Revision ID: 041
Revises: 040
Create Date: 2026-07-30 00:00:00.000000

Прогноз «когда будет результат» невозможно строить по created_at/updated_at:
их разница включает многочасовое ожидание в очереди. Нужны отдельные отметки
старта и конца ОБРАБОТКИ, плюс объём работы (позиции / страницы / строки),
зафиксированный при создании задачи. Все поля nullable: старые задачи остаются
без них и просто не участвуют в калибровке. Идемпотентно (IF NOT EXISTS).
"""
from typing import Sequence, Union
from alembic import op

revision: str = "041"
down_revision: Union[str, None] = "040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS volume_units INTEGER")
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS volume_kind VARCHAR(16)")
    # Калибровка ставок читает завершённые задачи по типу и времени завершения —
    # индекс держит этот запрос дешёвым на каждом открытии дашборда.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_type_finished "
        "ON tasks (task_type, finished_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tasks_type_finished")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS volume_kind")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS volume_units")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS finished_at")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS started_at")

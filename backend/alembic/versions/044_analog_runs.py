"""Поиск аналогов через ИИ: прогоны и найденные варианты

Revision ID: 044
Revises: 043
Create Date: 2026-08-03 00:00:00.000000

План: plans/2026-08-02-edinyy-redaktor-tablic.md, Фаза 11.

Поиск аналогов идёт в интернете через Claude, стоит денег и занимает минуты,
поэтому выполняется фоновой задачей. Здесь хранится состояние прогона: что
искали, что нашли, сколько позиций уже пройдено. Найденные варианты в документ
сами не попадают — они предложение, которое человек принимает кнопкой
«Заменить».

Все операции идемпотентны (IF NOT EXISTS): миграцию безопасно перезапускать.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "044"
down_revision: Union[str, None] = "043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analog_runs (
            id UUID PRIMARY KEY,
            task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            document_kind VARCHAR(30) NOT NULL,
            version_id UUID,
            status VARCHAR(12) NOT NULL DEFAULT 'queued',
            requested JSON NOT NULL DEFAULT '[]',
            results JSON NOT NULL DEFAULT '[]',
            processed INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            user_id INTEGER,
            user_name VARCHAR(120),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analog_runs_task_id ON analog_runs (task_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analog_runs_status ON analog_runs (status)"
    )
    # Поиск «есть ли уже прогон по этому документу» идёт по паре задача+тип.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analog_runs_task_kind "
        "ON analog_runs (task_id, document_kind)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analog_runs")

"""Журнал корректировок: «система посчитала X — человек поставил Y»

Revision ID: 046
Revises: 045
Create Date: 2026-08-07 00:00:00.000000

План: plans/2026-08-07-obuchenie-na-korrektirovkah.md, Фаза 1.

Отдельная таблица, а не расширение `task_history`: история обрезается до 20
записей на документ (она хранит снимки строк для отката и читается редактором
при каждом открытии), а знание об ошибке системы обрезать нельзя. Откат правки
удаляет запись истории, но не должен стирать сигнал.

Индексы:
* по `task_id` — выборка сигналов задачи;
* по `created_at` — лента последних расхождений в отчёте;
* составной `(task_id, document_kind, row_key, field)` — им проверяется
  «первое касание» ячейки одним запросом на применение, а не по строке на
  каждое изменение.

Все операции идемпотентны (IF NOT EXISTS): миграцию безопасно перезапускать.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "046"
down_revision: Union[str, None] = "045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS correction_signals (
            id UUID PRIMARY KEY,
            task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            document_kind VARCHAR(30) NOT NULL,
            row_key VARCHAR(80) NOT NULL,
            row_name TEXT,
            row_type VARCHAR(20),
            unit VARCHAR(50),
            field VARCHAR(200) NOT NULL,
            previous_value TEXT,
            new_value TEXT,
            previous_num NUMERIC(16, 4),
            new_num NUMERIC(16, 4),
            is_first_touch BOOLEAN NOT NULL DEFAULT true,
            price_source TEXT,
            user_id INTEGER,
            user_name VARCHAR(120),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_correction_signals_task_id "
        "ON correction_signals (task_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_correction_signals_created_at "
        "ON correction_signals (created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_correction_signals_cell "
        "ON correction_signals (task_id, document_kind, row_key, field)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_correction_signals_cell")
    op.execute("DROP INDEX IF EXISTS ix_correction_signals_created_at")
    op.execute("DROP INDEX IF EXISTS ix_correction_signals_task_id")
    op.execute("DROP TABLE IF EXISTS correction_signals")

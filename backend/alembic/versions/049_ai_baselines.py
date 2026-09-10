"""Снимок первичного вывода ИИ: что модель выдала до правок человека

Revision ID: 049
Revises: 048
Create Date: 2026-09-10 00:00:00.000000

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 1.

Для перечня и полноты первичный вывод ИИ сегодня не сохраняется нигде: правки
пишутся в ту же версию V0, а `_sync_task_items` переписывает и позиции задачи.
Эта таблица хранит строки такими, какими их выдал ИИ, — один раз, без
перезаписи. Уникальный индекс по паре «задача + тип документа» и есть та самая
защита: повторный прогон задачи не подменит снимок правлеными строками.

Все операции идемпотентны (IF NOT EXISTS): миграцию безопасно перезапускать.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "049"
down_revision: Union[str, None] = "048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_baselines (
            id UUID PRIMARY KEY,
            task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            document_kind VARCHAR(30) NOT NULL,
            rows JSON NOT NULL DEFAULT '[]',
            row_count INTEGER NOT NULL DEFAULT 0,
            truncated BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_baselines_task_id "
        "ON ai_baselines (task_id)"
    )
    # Пара «задача + документ» уникальна: снимок один и переписать его нельзя.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_baselines_task_kind "
        "ON ai_baselines (task_id, document_kind)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_baselines")

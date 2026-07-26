"""S3-миграция файлов (contract): DROP пустых BLOB-колонок

Revision ID: 035
Revises: 034
Create Date: 2026-07-26 00:00:00.000000

Contract-фаза паттерна expand→migrate→contract. Backfill на проде завершён
(остаток BLOB без storage_key = 0/0), код читает/пишет только через S3 по
storage_key. Дропаем пустые BLOB-колонки:
    - task_input_files.content
    - task_results.file_data

Legacy `tasks.input_file_data` НЕ трогаем: это живой JSON метаданных
(name/mime/size), а не BLOB — новые задачи пишут туда, листинг читает.

Идемпотентно: DROP COLUMN IF EXISTS (повторный прогон — no-op). downgrade
восстанавливает колонки nullable (без данных — байты остаются в S3).
"""
from typing import Sequence, Union
from alembic import op

revision: str = "035"
down_revision: Union[str, None] = "034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE task_input_files DROP COLUMN IF EXISTS content")
    op.execute("ALTER TABLE task_results DROP COLUMN IF EXISTS file_data")


def downgrade() -> None:
    # Восстановление только структуры (nullable) — байты остаются в S3, обратно
    # в БД не переносятся. Откат нужен лишь для отмены схемы, не данных.
    op.execute("ALTER TABLE task_input_files ADD COLUMN IF NOT EXISTS content BYTEA")
    op.execute("ALTER TABLE task_results ADD COLUMN IF NOT EXISTS file_data BYTEA")

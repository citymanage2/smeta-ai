"""S3-миграция файлов (expand): storage_key + BLOB → nullable

Revision ID: 034
Revises: 033
Create Date: 2026-07-25 00:00:00.000000

Expand-фаза паттерна expand→migrate→contract: добавляем nullable-колонку
storage_key в task_input_files и task_results и снимаем NOT NULL с BLOB-колонок
(content/file_data), чтобы после переноса в S3 их можно было обнулить. BLOB не
дропаем — до contract-фазы (миграция 035) работает dual-read fallback.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "034"
down_revision: Union[str, None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE task_input_files ADD COLUMN IF NOT EXISTS storage_key VARCHAR(500)")
    op.execute("ALTER TABLE task_input_files ALTER COLUMN content DROP NOT NULL")
    op.execute("ALTER TABLE task_results ADD COLUMN IF NOT EXISTS storage_key VARCHAR(500)")
    op.execute("ALTER TABLE task_results ALTER COLUMN file_data DROP NOT NULL")


def downgrade() -> None:
    # Best-effort откат: восстановление NOT NULL упадёт, если часть байтов уже в S3
    # (content/file_data = NULL). Это ожидаемо — downgrade после переноса не применяют.
    op.execute("ALTER TABLE task_results DROP COLUMN IF EXISTS storage_key")
    op.execute("ALTER TABLE task_results ALTER COLUMN file_data SET NOT NULL")
    op.execute("ALTER TABLE task_input_files DROP COLUMN IF EXISTS storage_key")
    op.execute("ALTER TABLE task_input_files ALTER COLUMN content SET NOT NULL")

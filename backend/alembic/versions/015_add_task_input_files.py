"""Добавить таблицу task_input_files для хранения файлов задач отдельно от JSON-колонки

Revision ID: 015
Revises: 014
Create Date: 2026-04-23 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS task_input_files (
            id          SERIAL PRIMARY KEY,
            task_id     UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            file_index  INTEGER NOT NULL,
            file_name   VARCHAR(500) NOT NULL,
            mime_type   VARCHAR(100) NOT NULL,
            size_bytes  INTEGER NOT NULL,
            content     BYTEA NOT NULL
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_task_input_files_task_id ON task_input_files (task_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS task_input_files")

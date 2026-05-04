"""Добавить таблицу api_call_log для трекинга стоимости Claude API

Revision ID: 020
Revises: 019
Create Date: 2026-05-04 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_call_log (
            id SERIAL PRIMARY KEY,
            task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
            model VARCHAR(50),
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd DECIMAL(10, 6) NOT NULL DEFAULT 0,
            called_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_call_log_task_id ON api_call_log(task_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_call_log_called_at ON api_call_log(called_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_api_call_log_called_at")
    op.execute("DROP INDEX IF EXISTS ix_api_call_log_task_id")
    op.execute("DROP TABLE IF EXISTS api_call_log")

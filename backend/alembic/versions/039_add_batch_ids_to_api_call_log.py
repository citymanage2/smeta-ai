"""Идентификаторы batch-записи в api_call_log (защита от дублей при пересборе)

Revision ID: 039
Revises: 038
Create Date: 2026-07-28 00:00:00.000000

resume_from_batch идемпотентен: после рестарта поллера пачка собирается заново,
и collect_claude_batch логировал те же вызовы повторно — метрика завышалась
(реальных денег это не стоило). По (batch_id, batch_custom_id) повтор теперь
распознаётся и пропускается. Для обычных вызовов обе колонки NULL. Идемпотентно.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "039"
down_revision: Union[str, None] = "038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE api_call_log ADD COLUMN IF NOT EXISTS batch_id VARCHAR(100)")
    op.execute("ALTER TABLE api_call_log ADD COLUMN IF NOT EXISTS batch_custom_id VARCHAR(100)")
    # Индекс частичный: обычные вызовы (batch_id IS NULL) в него не попадают.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_api_call_log_batch_entry "
        "ON api_call_log (batch_id, batch_custom_id) WHERE batch_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_api_call_log_batch_entry")
    op.execute("ALTER TABLE api_call_log DROP COLUMN IF EXISTS batch_custom_id")
    op.execute("ALTER TABLE api_call_log DROP COLUMN IF EXISTS batch_id")

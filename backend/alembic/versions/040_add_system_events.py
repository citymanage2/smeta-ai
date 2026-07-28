"""Таблица системных событий (уведомление о восстановлении баланса API)

Revision ID: 040
Revises: 039
Create Date: 2026-07-28 00:00:00.000000

Событие «баланс пополнен, задачи возобновлены» рождается в worker-процессе, а
показать его нужно в браузере — нужна общая точка хранения, переживающая рестарт
воркера и закрытую вкладку. Идемпотентно (IF NOT EXISTS).
"""
from typing import Sequence, Union
from alembic import op

revision: str = "040"
down_revision: Union[str, None] = "039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS system_events (
            id BIGSERIAL PRIMARY KEY,
            kind VARCHAR(40) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_system_events_kind_id ON system_events (kind, id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_system_events_kind_id")
    op.execute("DROP TABLE IF EXISTS system_events")

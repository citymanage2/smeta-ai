"""Правила для промпта, включаемые человеком

Revision ID: 051
Revises: 050
Create Date: 2026-09-14 00:00:00.000000

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 8.

Все операции идемпотентны (IF NOT EXISTS): миграцию безопасно перезапускать.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "051"
down_revision: Union[str, None] = "050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_rules (
            id SERIAL PRIMARY KEY,
            text TEXT NOT NULL,
            scope VARCHAR(50) NOT NULL DEFAULT 'ALL',
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            created_by VARCHAR(120),
            enabled_by VARCHAR(120),
            enabled_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_prompt_rules_enabled ON prompt_rules (enabled)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prompt_rules")

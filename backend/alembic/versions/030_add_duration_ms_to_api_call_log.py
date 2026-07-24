"""Добавить колонку duration_ms в api_call_log (наблюдаемость: длительность API-вызова Claude)

Revision ID: 030
Revises: 029
Create Date: 2026-07-24 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE api_call_log "
        "ADD COLUMN IF NOT EXISTS duration_ms INTEGER"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE api_call_log DROP COLUMN IF EXISTS duration_ms")

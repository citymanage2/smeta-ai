"""Число web-поисков в api_call_log (отдельная статья счёта Anthropic)

Revision ID: 038
Revises: 037
Create Date: 2026-07-28 00:00:00.000000

web search тарифицируется отдельно от токенов ($10 / 1000 поисков) и в
cost_usd не входил вовсе. Замер 28.07.2026: $35.88 из $161.06 за неделю —
22% счёта, невидимых в метрике. Колонка нужна, чтобы считать честно.
Старые строки остаются с 0 — там значение неизвестно. Идемпотентно.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "038"
down_revision: Union[str, None] = "037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE api_call_log "
        "ADD COLUMN IF NOT EXISTS web_search_requests INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE api_call_log DROP COLUMN IF EXISTS web_search_requests")

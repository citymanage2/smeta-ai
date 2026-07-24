"""Durable-очередь задач: таблица jobs + индексы под claim и fairness

Revision ID: 033
Revises: 032
Create Date: 2026-07-24 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "033"
down_revision: Union[str, None] = "032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id BIGSERIAL PRIMARY KEY,
            kind VARCHAR(40) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            owner_id INTEGER,
            status VARCHAR(10) NOT NULL DEFAULT 'queued',
            priority INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            claimed_by VARCHAR(64),
            claimed_at TIMESTAMPTZ,
            last_error VARCHAR(1000),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_claim ON jobs (status, priority, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_owner_status ON jobs (owner_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_owner_status")
    op.execute("DROP INDEX IF EXISTS ix_jobs_claim")
    op.execute("DROP TABLE IF EXISTS jobs")

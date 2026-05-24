"""Добавить таблицы training_pairs и training_jobs для дообучения модели эмбеддингов

Revision ID: 028
Revises: 027
Create Date: 2026-05-25 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS training_pairs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            anchor_text TEXT NOT NULL,
            candidate_text TEXT NOT NULL,
            candidate_type VARCHAR(20) NOT NULL,
            is_positive BOOLEAN NOT NULL,
            similarity_score FLOAT NOT NULL,
            source_file VARCHAR(255),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_training_pairs_is_positive
        ON training_pairs (is_positive)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_training_pairs_created_at
        ON training_pairs (created_at)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS training_jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            pairs_count INTEGER NOT NULL DEFAULT 0,
            progress_pct INTEGER NOT NULL DEFAULT 0,
            progress_message TEXT,
            model_path VARCHAR(512),
            error TEXT,
            started_at TIMESTAMP WITH TIME ZONE,
            finished_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_training_jobs_status
        ON training_jobs (status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_training_jobs_created_at
        ON training_jobs (created_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS training_jobs")
    op.execute("DROP TABLE IF EXISTS training_pairs")

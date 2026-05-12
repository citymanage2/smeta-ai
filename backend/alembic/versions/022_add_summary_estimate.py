"""Создать таблицу summary_estimates

Revision ID: 022
Revises: 021
Create Date: 2026-05-12 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS summary_estimates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            sections JSONB NOT NULL DEFAULT '[]',
            overrides JSONB NOT NULL DEFAULT '{}',
            total_for_customer DECIMAL(14, 2) NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_summary_estimates_project UNIQUE (project_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_summary_estimates_project_id "
        "ON summary_estimates(project_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_summary_estimates_project_id")
    op.execute("DROP TABLE IF EXISTS summary_estimates")

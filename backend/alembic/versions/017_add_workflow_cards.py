"""Добавить таблицу workflow_cards для канбан-карточек

Revision ID: 017
Revises: 016
Create Date: 2026-04-29 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS workflow_cards (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            stage VARCHAR(20) NOT NULL DEFAULT 'list'
                CONSTRAINT ck_workflow_cards_stage
                CHECK (stage IN ('list','completeness','estimate','optimization')),
            list_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
            completeness_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
            estimate_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
            optimization_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_workflow_cards_project_id
        ON workflow_cards(project_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_workflow_cards_project_id")
    op.execute("DROP TABLE IF EXISTS workflow_cards")

"""Добавить составной индекс tasks(project_id, estimation_status)

Revision ID: 013
Revises: 012
Create Date: 2026-04-22 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_project_estimation "
        "ON tasks (project_id, estimation_status)"
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_project_estimation", table_name="tasks")

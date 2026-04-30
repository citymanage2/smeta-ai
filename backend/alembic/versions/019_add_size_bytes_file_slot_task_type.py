"""Добавить size_bytes в task_results; file_slot и task_type в estimate_versions

Revision ID: 019
Revises: 018
Create Date: 2026-04-30 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE task_results
        ADD COLUMN IF NOT EXISTS size_bytes INTEGER NOT NULL DEFAULT 0
    """)
    op.execute("""
        UPDATE task_results
        SET size_bytes = octet_length(file_data)
        WHERE size_bytes = 0 AND file_data IS NOT NULL
    """)
    op.execute("""
        ALTER TABLE estimate_versions
        ADD COLUMN IF NOT EXISTS file_slot VARCHAR(20) NOT NULL DEFAULT 'result'
    """)
    op.execute("""
        ALTER TABLE estimate_versions
        ADD COLUMN IF NOT EXISTS task_type VARCHAR(50) NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE task_results DROP COLUMN IF EXISTS size_bytes")
    op.execute("ALTER TABLE estimate_versions DROP COLUMN IF EXISTS file_slot")
    op.execute("ALTER TABLE estimate_versions DROP COLUMN IF EXISTS task_type")

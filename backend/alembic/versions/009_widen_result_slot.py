"""Widen task_results.slot from VARCHAR(20) to VARCHAR(50) for versioned slots

Revision ID: 009
Revises: 008
Create Date: 2026-04-09 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE task_results ALTER COLUMN slot TYPE VARCHAR(50)")


def downgrade() -> None:
    op.alter_column(
        "task_results",
        "slot",
        existing_type=sa.String(50),
        type_=sa.String(20),
        existing_nullable=False,
    )

"""Widen estimation_status column to VARCHAR(50)

Revision ID: 007
Revises: 006
Create Date: 2026-03-27 00:00:00.000000

Context: production StringDataRightTruncationError — value
'processing_optimization' (23 chars) exceeded VARCHAR(20).
Renamed status to 'optimizing' (10 chars) and widened column to
VARCHAR(50) to prevent similar issues in the future.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "tasks",
        "estimation_status",
        type_=sa.String(50),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "tasks",
        "estimation_status",
        type_=sa.String(20),
        existing_nullable=False,
    )

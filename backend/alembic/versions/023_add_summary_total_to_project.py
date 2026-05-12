"""Добавить summary_total в projects

Revision ID: 023
Revises: 022
Create Date: 2026-05-12 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS summary_total DECIMAL(14, 2)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS summary_total")

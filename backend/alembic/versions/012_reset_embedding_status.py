"""Reset embedding_status to pending after switching to Cohere

Revision ID: 012
Revises: 011
Create Date: 2026-04-20 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE price_lists SET embedding_status = 'pending'")


def downgrade() -> None:
    pass

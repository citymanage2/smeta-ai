"""Добавить deleted_at к workflow_cards для soft delete карточек

Revision ID: 027
Revises: 026
Create Date: 2026-05-24 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE workflow_cards ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workflow_cards_deleted_at "
        "ON workflow_cards (deleted_at)"
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_cards_deleted_at", table_name="workflow_cards")
    op.drop_column("workflow_cards", "deleted_at")

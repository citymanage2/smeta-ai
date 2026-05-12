"""Добавить primary_version_id в workflow_cards

Revision ID: 021
Revises: 020
Create Date: 2026-05-12 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE workflow_cards
        ADD COLUMN IF NOT EXISTS primary_version_id UUID
            REFERENCES estimate_versions(id) ON DELETE SET NULL
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workflow_cards_primary_version_id "
        "ON workflow_cards(primary_version_id)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_workflow_cards_primary_version_id"
    )
    op.execute(
        "ALTER TABLE workflow_cards DROP COLUMN IF EXISTS primary_version_id"
    )

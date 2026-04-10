"""Add embedding columns to price_works, price_materials and embedding_status to price_lists

Revision ID: 010
Revises: 009
Create Date: 2026-04-10 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE price_works ADD COLUMN IF NOT EXISTS embedding JSONB")
    op.execute("ALTER TABLE price_materials ADD COLUMN IF NOT EXISTS embedding JSONB")
    op.execute(
        "ALTER TABLE price_lists ADD COLUMN IF NOT EXISTS embedding_status "
        "VARCHAR(20) NOT NULL DEFAULT 'pending'"
    )


def downgrade() -> None:
    op.drop_column("price_lists", "embedding_status")
    op.drop_column("price_materials", "embedding")
    op.drop_column("price_works", "embedding")

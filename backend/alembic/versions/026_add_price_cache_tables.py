"""Добавить таблицы кеша цен из веб-поиска

Revision ID: 026
Revises: 025
Create Date: 2026-05-23 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS price_cache_works (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name        TEXT NOT NULL,
            unit        TEXT,
            price       NUMERIC(12,2) NOT NULL,
            sources     TEXT,
            embedding   JSONB,
            created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS price_cache_materials (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name        TEXT NOT NULL,
            unit        TEXT,
            price       NUMERIC(12,2) NOT NULL,
            sources     TEXT,
            embedding   JSONB,
            created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_price_cache_works_updated_at ON price_cache_works (updated_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_price_cache_materials_updated_at ON price_cache_materials (updated_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_price_cache_materials_updated_at")
    op.execute("DROP INDEX IF EXISTS ix_price_cache_works_updated_at")
    op.execute("DROP TABLE IF EXISTS price_cache_materials")
    op.execute("DROP TABLE IF EXISTS price_cache_works")

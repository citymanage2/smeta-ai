"""Добавить name_norm + индекс в price_cache_works/materials (прямой поиск вместо скана)

Revision ID: 031
Revises: 030
Create Date: 2026-07-24 00:00:00.000000

Бэкфилл реплицирует normalize_text(): lower + trim + ё→е + сжатие пробелов.
Миграции применяются только на PostgreSQL (прод/docker), поэтому используется
regexp_replace. Тесты (SQLite) создают схему через create_all по моделям.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "031"
down_revision: Union[str, None] = "030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Нормализация имени в SQL (эквивалент normalize_text в Python).
_NORM_SQL = "regexp_replace(lower(trim(replace(name, 'ё', 'е'))), '\\s+', ' ', 'g')"


def upgrade() -> None:
    for table in ("price_cache_works", "price_cache_materials"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS name_norm TEXT")
        op.execute(f"UPDATE {table} SET name_norm = {_NORM_SQL} WHERE name_norm IS NULL")
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_{table}_name_norm ON {table} (name_norm)"
        )


def downgrade() -> None:
    for table in ("price_cache_works", "price_cache_materials"):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_name_norm")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS name_norm")

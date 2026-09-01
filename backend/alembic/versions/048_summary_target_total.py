"""Цель по объекту — витрина в projects для списка проектов

Revision ID: 048
Revises: 047
Create Date: 2026-09-01 00:00:00.000000

План: plans/2026-09-01-celi-optimizacii.md, Фаза 2.

Сами цели оптимизации миграции не требуют: цель раздела — поле внутри JSON
`summary_estimates.sections`, база целей и цель по объекту — внутри JSON
`summary_estimates.overrides`.

Колонка здесь нужна только списку проектов: он собирается групповым запросом по
колонкам, а JSON в GROUP BY PostgreSQL не принимает. Значение — копия
`overrides.target_total_for_customer`, которая пишется там же, где
`projects.summary_total`.

Операция идемпотентна (IF NOT EXISTS): миграцию безопасно перезапускать.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "048"
down_revision: Union[str, None] = "047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS summary_target_total NUMERIC(14, 2)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS summary_target_total")

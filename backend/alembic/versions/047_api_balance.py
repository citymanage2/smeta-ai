"""Остаток денег на Claude API: пополнения и официальные траты по дням

Revision ID: 047
Revises: 046
Create Date: 2026-09-01 00:00:00.000000

План: plans/2026-09-01-ostatok-deneg-na-api.md, Фаза 2.

Две таблицы:

* `api_balance_marks` — отметка «на такую-то дату на счету было $X». Точку
  отсчёта не отдаёт ни один API Anthropic, её вводит человек. Индекс по дате —
  под выборку последней отметки, от которой считается остаток.
* `api_cost_days` — официальная стоимость закрытого дня из `cost_report`.
  Ключ — сам день, поэтому повторная синхронизация перезаписывает строку и не
  может задвоить сумму.

Все операции идемпотентны (IF NOT EXISTS): миграцию безопасно перезапускать.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "047"
down_revision: Union[str, None] = "046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_balance_marks (
            id SERIAL PRIMARY KEY,
            balance_usd NUMERIC(12, 2) NOT NULL,
            measured_on DATE NOT NULL,
            note TEXT,
            created_by VARCHAR(120),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_api_balance_marks_measured_on "
        "ON api_balance_marks (measured_on)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_cost_days (
            day DATE PRIMARY KEY,
            amount_usd NUMERIC(12, 6) NOT NULL,
            synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_cost_days")
    op.execute("DROP INDEX IF EXISTS ix_api_balance_marks_measured_on")
    op.execute("DROP TABLE IF EXISTS api_balance_marks")

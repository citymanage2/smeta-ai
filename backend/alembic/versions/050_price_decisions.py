"""Решения по выученным ценам + индекс под очередь предложений

Revision ID: 050
Revises: 049
Create Date: 2026-09-10 00:00:00.000000

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 6.

Предложения цен не хранятся — они считаются из `correction_signals` на лету.
Здесь только решения человека: что он запомнил и что отклонил. Без них
отклонённое предложение возвращалось бы после каждой следующей правки той же
позиции.

Второй частью — индекс под сам запрос предложений: он отбирает первые касания
ценовых полей, и без индекса это последовательное чтение всего журнала,
которое будет дорожать с каждой правкой.

Все операции идемпотентны (IF NOT EXISTS): миграцию безопасно перезапускать.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "050"
down_revision: Union[str, None] = "049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS price_decisions (
            id UUID PRIMARY KEY,
            name_key VARCHAR(500) NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            row_type VARCHAR(20) NOT NULL DEFAULT 'work',
            unit VARCHAR(50) NOT NULL DEFAULT '',
            decision VARCHAR(20) NOT NULL,
            price DOUBLE PRECISION,
            user_id INTEGER,
            user_name VARCHAR(120),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_price_decisions_name_key "
        "ON price_decisions (name_key)"
    )
    # Позиция решается один раз: имя + тип + единица. Одноимённая позиция бывает
    # и работой, и материалом, а цена за «м2» и за «м3» — разные цены.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_price_decisions_position "
        "ON price_decisions (name_key, row_type, unit)"
    )
    # Очередь предложений читает только первые касания ценовых полей сметы.
    # Частичный индекс держит в себе ровно эти строки — их в журнале меньшинство.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_correction_signals_price_touch
        ON correction_signals (document_kind, field)
        WHERE is_first_touch AND field IN ('price_work', 'price_material')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_correction_signals_price_touch")
    op.execute("DROP TABLE IF EXISTS price_decisions")

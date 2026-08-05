"""Признак «дополнительный запрос» в журнале вызовов ИИ

Revision ID: 045
Revises: 044
Create Date: 2026-08-06 00:00:00.000000

План: plans/2026-08-06-metriki-zatrat-po-stadiyam.md, Фаза 1.

Стадия сметы стоит денег дважды: сначала обработчик формирует файл, потом
человек в редакторе доспрашивает ИИ — ищет цену строки, аналоги, предложения по
оптимизации. Второе идёт по уже готовому файлу и в карточке показывается
отдельной цифрой «допы», иначе непонятно, где именно утекают деньги.

Признак явный, а не вычисляемый по времени (`called_at > tasks.finished_at`):
перезапуск задачи переставляет `finished_at`, и прежние допы задним числом
стали бы основными — цифра меняла бы смысл от постороннего действия.

Существующие строки остаются `false`: восстановить их принадлежность задним
числом нечем, а почти все они и были основной обработкой.

Все операции идемпотентны (IF NOT EXISTS): миграцию безопасно перезапускать.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "045"
down_revision: Union[str, None] = "044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE api_call_log "
        "ADD COLUMN IF NOT EXISTS is_extra BOOLEAN NOT NULL DEFAULT false"
    )
    # Метрики карточки считаются одним GROUP BY по task_id с разбиением по
    # is_extra — составной индекс закрывает запрос без похода в таблицу.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_api_call_log_task_extra "
        "ON api_call_log (task_id, is_extra)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_api_call_log_task_extra")
    op.execute("ALTER TABLE api_call_log DROP COLUMN IF EXISTS is_extra")

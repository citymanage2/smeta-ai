"""Снимок строк, как их выдал ИИ, — до единой правки человека.

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 1.

Зачем отдельная таблица, если строки документа и так лежат в `EstimateVersion`:
у версии другая работа. Для перечня и полноты правки пишутся **в ту же самую**
версию V0 (слот `result` у этих типов один), а `document_service._sync_task_items`
переписывает ещё и `task.progress_data['items']` — это правило 6 CLAUDE.md, без
него правки перечня не доезжали бы до сметы. То есть после первого «Применить»
первичный вывод модели не восстановить ниоткуда: ни версия, ни позиции задачи,
ни файл результата его больше не помнят.

Поэтому снимок живёт своей записью и подчиняется правилу входного файла
заказчика (правило 2 CLAUDE.md): **пишется один раз и не перезаписывается
никогда**. Уникальность по паре «задача + тип документа» — не оптимизация, а
защита: повторный прогон задачи (resume, batch) не имеет права подменить снимок
строками, которые человек уже поправил.

Что здесь **не** хранится: текущее состояние документа. Снимок отвечает ровно на
один вопрос — «что выдал ИИ», — и сравнивать его с сегодняшними строками дело
`services/reconciliation.py`.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base

# Потолок числа строк в снимке. Колонка — обычный JSON (текст), а движок пишет
# его с `ensure_ascii`, поэтому каждая кириллическая буква занимает шесть байт:
# строка перечня выходит ≈1,3 КБ, строка сметы ≈0,9 КБ. То есть 2500 строк это
# уже около 3 МБ в одном значении. Реальная смета — сотни строк, редко больше
# двух тысяч, так что потолок режет только патологию. Сверх него снимок
# пишется усечённым и честно об этом говорит — половина ответа лучше
# отсутствующего.
MAX_BASELINE_ROWS = 2500


class AiBaseline(Base):
    __tablename__ = "ai_baselines"
    __table_args__ = (
        UniqueConstraint("task_id", "document_kind", name="uq_ai_baselines_task_kind"),
    )

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(_uuid.uuid4())
    )
    task_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # list | completeness | estimate — те же значения, что у документов
    # (`document_service.DOCUMENT_KINDS`). Оптимизация и раздел сводной снимка не
    # имеют: их строки — результат работы над чужим расчётом, а не вывод ИИ.
    document_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # Строки ровно в том виде, в каком они легли в рабочую версию. Копия, а не
    # повторный разбор файла: `xlsx_generic` выдаёт новый `row_id` на каждый
    # разбор, и снимок с чужими идентификаторами не сопоставился бы ни с одной
    # сегодняшней строкой.
    rows: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # True — строк было больше потолка, снимок неполный.
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover — диагностика в логах
        return (
            f"<AiBaseline task={self.task_id} kind={self.document_kind} "
            f"rows={self.row_count}{' truncated' if self.truncated else ''}>"
        )


__all__ = ["AiBaseline", "MAX_BASELINE_ROWS"]

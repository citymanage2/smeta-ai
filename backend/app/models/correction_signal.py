"""Сигнал корректировки: «система посчитала X — человек поставил Y».

План: plans/2026-08-07-obuchenie-na-korrektirovkah.md, Фаза 1.

Зачем отдельная таблица, если правки уже пишутся в `task_history`: у истории
другая работа и другой срок жизни. Она обрезается до 20 записей на документ
(`document_service.HISTORY_DEPTH`), потому что хранит снимки строк для отката и
читается редактором при каждом открытии документа. Знание «система тут ошиблась»
обрезать нельзя, а откат правки не должен его стирать — это разные сущности,
случайно похожие по форме.

Что здесь **не** хранится: решение, что делать со знанием. Журнал только
копится; применение (цена в прайс, обучающая пара, правило в промпт) идёт
отдельным шагом и только после подтверждения человеком — решение пользователя
от 07.08.2026.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Поле-заполнитель для сигналов «строка добавлена» и «строка удалена»: у них нет
# конкретной ячейки, но сами по себе они — самый ценный сигнал (система пропустила
# позицию или выдумала лишнюю).
FIELD_ROW = "__row"


class CorrectionSignal(Base):
    __tablename__ = "correction_signals"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(_uuid.uuid4())
    )
    task_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # list | completeness | estimate | optimization | summary-section
    document_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # Идентификатор строки; у строк без него — позиционный ключ `__pos_N`,
    # ровно тот же, по которому строки сопоставляет `document_service.diff_rows`.
    row_key: Mapped[str] = mapped_column(String(80), nullable=False)
    row_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # work | material | section — у generic-строк берётся из ячейки «Тип».
    row_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Машинный ключ поля: `price_work`, `qty`, … У перечня и полноты — имя
    # колонки исходного файла. Русская подпись здесь не годится: по ней не
    # сгруппируешь и не применишь знание.
    field: Mapped[str] = mapped_column(String(200), nullable=False)
    # Текстовое представление — годится для любого поля; числовое рядом, чтобы
    # считать величину промаха, не разбирая строки на каждый отчёт.
    previous_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    previous_num: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 4), nullable=True)
    new_num: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 4), nullable=True)
    # True — ячейку правят впервые после того, как её заполнила система: только
    # такой сигнал говорит об ошибке системы. Правка правки — разговор человека с
    # самим собой, в отчёт о качестве не идёт.
    is_first_touch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Откуда система взяла цену (`price_list_name` строки): прайс, кеш прошлых
    # задач или веб-поиск. Без этого непонятно, что именно чинить.
    price_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

"""Решение человека по предложенной цене: запомнить или не запоминать.

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 6.

Сами предложения не хранятся: они считаются на лету из журнала корректировок.
Хранить их таблицей значило бы держать вторую копию знания в согласии с
растущим журналом и завести второго писателя в горячем пути «Применить» — а он
уже сейчас глотает свои ошибки, чтобы не уронить правку.

Здесь лежит только то, чего в журнале нет и быть не может: что человек с этим
знанием решил. Без такой записи отклонённое предложение всплывало бы снова при
каждой следующей правке той же позиции.

Ключ решения — не одно имя: одноимённая позиция бывает и работой, и
материалом, а цена за «м2» и за «м3» назначена за разное (правило 8 CLAUDE.md).
Поэтому в ключ входят нормализованное имя, тип строки и единица.

Решение не вечно. Записанная рядом цена (`price`) отвечает на вопрос «что
именно отклонили»: если человек потом станет ставить заметно другую цену, это
новое знание, и предложение появится снова. Та же цена — не всплывёт.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime, Float, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

DECISION_ACCEPTED = "accepted"
DECISION_REJECTED = "rejected"


class PriceDecision(Base):
    __tablename__ = "price_decisions"
    __table_args__ = (
        UniqueConstraint(
            "name_key", "row_type", "unit", name="uq_price_decisions_position"
        ),
    )

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(_uuid.uuid4())
    )
    # `embedding_service.normalize_name` — тот же ключ «та же позиция», которым
    # прайс ищет существующую строку при записи. Своего определения заводить
    # нельзя: разошлись бы решение и запись.
    name_key: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    # Как позиция называлась у человека — для показа в списке отклонённых.
    display_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    row_type: Mapped[str] = mapped_column(String(20), nullable=False, default="work")
    unit: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    # accepted | rejected
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    # Цена, о которой шла речь. Отклонили именно её, а не позицию навсегда.
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


__all__ = ["PriceDecision", "DECISION_ACCEPTED", "DECISION_REJECTED"]

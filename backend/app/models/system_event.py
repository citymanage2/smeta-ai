"""Системные события — то, что происходит в воркере, а показать надо в браузере.

Воркер и web — разные процессы, поэтому событие «баланс API пополнен, задачи
возобновлены» нельзя удержать в памяти: web его не увидит. Плюс пауза по балансу
длится часами, и к моменту восстановления вкладка пользователя почти наверняка
перезагружена (`trackedTasks` во фронте не персистентны). Отсюда — строка в БД
и курсорный опрос `GET /notifications/system?since_id=N`.

Payload намеренно хранит только id задач: названия и права видимости берутся из
актуальной таблицы `tasks` в момент отдачи, поэтому рассинхрона не бывает.

План: plans/2026-07-28-balance-restored-notification.md, Фаза 1.
"""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy import JSON as _JSON
from sqlalchemy.dialects.postgresql import JSONB as _JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# JSONB на PostgreSQL, JSON на SQLite (тесты) — как в models/job.py
JSONB = _JSON().with_variant(_JSONB(), "postgresql")

# Единственный вид событий на сегодня. Строкой, а не Enum: добавление нового вида
# не должно требовать миграции.
KIND_BALANCE_RESTORED = "balance_restored"


class SystemEvent(Base):
    __tablename__ = "system_events"
    __table_args__ = (
        # Под выборку «события вида X новее курсора»: WHERE kind=… AND id > N.
        Index("ix_system_events_kind_id", "kind", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

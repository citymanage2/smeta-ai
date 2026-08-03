import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Состояния прогона. Отменённый и упавший разделены намеренно: «я передумал» и
# «сломалось» человек должен видеть по-разному.
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)


class AnalogRun(Base):
    """Прогон поиска аналогов по выделенным позициям (план 2026-08-02, Фаза 11).

    Поиск идёт в интернете через Claude и стоит денег, поэтому он вынесен в
    фоновую задачу: человек не ждёт у экрана, а видит прогресс и может
    остановить прогон.

    Найденные варианты — это **предложение**, а не правка: они лежат здесь и
    попадают в документ только тогда, когда человек нажал «Заменить». Правка
    при этом идёт через черновик редактора, поэтому отменяется Ctrl+Z.
    """

    __tablename__ = "analog_runs"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(_uuid.uuid4()),
    )
    task_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Тип документа: у одной задачи может быть несколько документов, и прогоны
    # по ним смешивать нельзя.
    document_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    version_id: Mapped[Optional[str]] = mapped_column(
        PG_UUID(as_uuid=False), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=STATUS_QUEUED, index=True
    )
    # Что искали: снимок позиций на момент запуска. Пока идёт поиск, человек
    # может править документ — без снимка результаты некуда было бы привязать.
    requested: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Что нашли: [{row_id, variants: [{name, unit, price, delta, reason, source}]}]
    results: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

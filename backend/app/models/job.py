from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import Integer, BigInteger, String, DateTime, Index
from sqlalchemy import JSON as _JSON
from sqlalchemy.dialects.postgresql import JSONB as _JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# JSONB на PostgreSQL, JSON на SQLite (тесты)
JSONB = _JSON().with_variant(_JSONB(), "postgresql")


class Job(Base):
    """Слой durable-очереди: claim/heartbeat/attempts.

    Отделён от доменного Task.status (тот остаётся источником правды для UI).
    Одна job может ссылаться на Task, EstimateVersion, training_job и т.п. —
    что именно, задаёт `kind` + `payload`.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        # Покрывает WHERE status='queued' в claim и вторичную сортировку
        # priority/created_at. NB: ведущий ключ ORDER BY в claim_one — коррелированный
        # running_ct (число running на владельца), его индекс не покрывает; при малой
        # очереди (десятки job) это несущественно, отдельный индекс не заводим.
        Index("ix_jobs_claim", "status", "priority", "created_at"),
        # Под подсчёт «running на владельца» (round-robin fairness).
        Index("ix_jobs_owner_status", "owner_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)  # task.process, task.optimize, ...
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    owner_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="queued")  # queued/running/done/failed
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # выше — раньше
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claimed_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

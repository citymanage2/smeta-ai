"""Присутствие в документе: «Иван сейчас редактирует».

Не блокировка в строгом смысле — сохранять другому не запрещаем, от затирания
защищает `EstimateVersion.rev`. Запись живёт, пока приходит heartbeat; протухает
за `LOCK_TTL_SECONDS` и перестаёт учитываться (чистится лениво, при следующем
обращении к документу — фоновый сборщик ради этого не нужен).
"""
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Клиент шлёт heartbeat раз в 20 секунд — три пропуска подряд считаем уходом.
LOCK_TTL_SECONDS = 90


class DocumentLock(Base):
    __tablename__ = "document_locks"
    __table_args__ = (
        UniqueConstraint("card_id", "kind", name="uq_document_locks_card_kind"),
    )

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(_uuid.uuid4()),
    )
    card_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("workflow_cards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # list | completeness | estimate | optimization | summary-section
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    user_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

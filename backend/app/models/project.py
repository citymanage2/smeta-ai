import uuid as _uuid
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Text, DateTime, Numeric, Integer, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from datetime import datetime, timezone
from app.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(_uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Владелец проекта (человек). nullable: legacy-проекты до backfill; при удалении
    # пользователя — SET NULL (удаление аккаунтов делаем soft, чтобы не осиротить).
    owner_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Архив: True → проект скрыт из основной панели, виден только в разделе «Архив».
    # Ортогонален правам (видимость/правка — по owner_id + роли).
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    # Общий: True → виден всем сотрудникам поверх изоляции по владельцу
    # (старые данные компании). Обычные проекты — false.
    is_shared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
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
    summary_total: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True, default=None
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

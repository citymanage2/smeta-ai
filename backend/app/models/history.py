import uuid as _uuid
from typing import Optional
from sqlalchemy import String, DateTime, JSON, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from datetime import datetime, timezone
from app.database import Base


class TaskHistory(Base):
    __tablename__ = "task_history"

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
    operation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    slot: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    previous_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    new_value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # --- Единый редактор (план 2026-08-02) ---
    # Автор правки: показываем «Иванов, 02.08.2026 14:31, изменил…».
    # nullable — у записей, созданных автоматикой (оптимизация, поиск цен).
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Тип документа, к которому относится правка (list | completeness | estimate | ...)
    document_kind: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

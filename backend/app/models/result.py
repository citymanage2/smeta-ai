from typing import Optional

from sqlalchemy import Integer, String, DateTime, LargeBinary, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from datetime import datetime, timezone
from app.database import Base


class TaskResult(Base):
    __tablename__ = "task_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # Ключ объекта в S3 (Phase 3+). Если задан — байты в S3, file_data=NULL.
    storage_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # BLOB стал nullable: при переносе в S3 обнуляется (fallback до contract-фазы).
    file_data: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    slot: Mapped[str] = mapped_column(String(50), nullable=False, default="result")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    task = relationship("Task", foreign_keys=[task_id])

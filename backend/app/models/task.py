import uuid as _uuid
from typing import Optional
from decimal import Decimal
from sqlalchemy import Integer, String, Text, DateTime, JSON, Numeric, ForeignKey
from sqlalchemy import JSON as _JSON
from sqlalchemy.dialects.postgresql import JSONB as _JSONB
# Используем JSONB на PostgreSQL, JSON на SQLite (тесты)
JSONB = _JSON().with_variant(_JSONB(), "postgresql")
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from datetime import datetime, timezone
from app.database import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(_uuid.uuid4()),
    )
    user_role: Mapped[str] = mapped_column(String(10), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    input_files: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Each entry: {name, mime_type, size_bytes, content_b64}
    input_file_data: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    user_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chat_history: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    progress_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    progress_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    project_id: Mapped[Optional[str]] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    estimation_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="not_applicable",
    )
    cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
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

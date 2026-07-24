from typing import Optional

from sqlalchemy import Integer, String, LargeBinary, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from app.database import Base


class TaskInputFile(Base):
    __tablename__ = "task_input_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_index: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Ключ объекта в S3 (Phase 3+). Если задан — байты в S3, content=NULL.
    storage_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # BLOB стал nullable: при переносе в S3 обнуляется (fallback до contract-фазы).
    content: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)

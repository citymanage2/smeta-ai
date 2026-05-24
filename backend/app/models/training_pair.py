import uuid
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from app.database import Base


class TrainingPair(Base):
    __tablename__ = "training_pairs"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    anchor_text: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_text: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "work" | "material"
    is_positive: Mapped[bool] = mapped_column(Boolean, nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    source_file: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

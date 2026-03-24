from typing import Optional
from sqlalchemy import String, Text, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import text, Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from datetime import datetime, timezone
from app.database import Base


class EstimateItem(Base):
    __tablename__ = "estimate_items"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    task_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)   # 'Работа' | 'Материал'
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    work_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mat_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    section: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_analogue: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    original_item_id: Mapped[Optional[str]] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("estimate_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    analogue_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # stores extra fields: price_list_name, sources, usn, material_price (legacy key), etc.
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
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

import uuid as _uuid
from typing import Optional
from sqlalchemy import String, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from datetime import datetime, timezone
from app.database import Base


class WorkflowCard(Base):
    __tablename__ = "workflow_cards"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('list','completeness','estimate','optimization')",
            name="ck_workflow_cards_stage",
        ),
    )

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(_uuid.uuid4()),
    )
    project_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="list")

    list_task_id: Mapped[Optional[str]] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    completeness_task_id: Mapped[Optional[str]] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    estimate_task_id: Mapped[Optional[str]] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    optimization_task_id: Mapped[Optional[str]] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    primary_version_id: Mapped[Optional[str]] = mapped_column(
        PG_UUID(as_uuid=False),
        ForeignKey("estimate_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    # lazy="raise" запрещает случайные N+1; загрузка только через selectinload
    list_task = relationship(
        "Task", foreign_keys=[list_task_id], lazy="raise"
    )
    completeness_task = relationship(
        "Task", foreign_keys=[completeness_task_id], lazy="raise"
    )
    estimate_task = relationship(
        "Task", foreign_keys=[estimate_task_id], lazy="raise"
    )
    optimization_task = relationship(
        "Task", foreign_keys=[optimization_task_id], lazy="raise"
    )

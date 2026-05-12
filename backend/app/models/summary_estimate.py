import uuid as _uuid
from decimal import Decimal
from typing import Any
from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from datetime import datetime, timezone
from app.database import Base


class SummaryEstimate(Base):
    __tablename__ = "summary_estimates"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_summary_estimates_project"),
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
        unique=True,
        index=True,
    )
    # [{card_id, card_name, version_id, rows: [EstimateRow]}]
    sections: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    # {transport_pct, cleanup_pct, overhead_pct, daily_workers_cost,
    #  bank_guarantee_cost, cleaning_cost, ppr_cost, commissioning_cost,
    #  contingency_pct, profit_pct, vat_works_pct, vat_materials_pct, tax_pct}
    overrides: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    total_for_customer: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0")
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

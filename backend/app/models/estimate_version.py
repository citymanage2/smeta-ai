from __future__ import annotations

import uuid as _uuid
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import String, DateTime, JSON, ForeignKey, Integer, Numeric, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from datetime import datetime, timezone
from app.database import Base


class EstimateVersion(Base):
    __tablename__ = "estimate_versions"

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
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Допустимые значения: original | client | completeness_checked | no_redundant | tech_optimized | material_optimized | custom
    version_label: Mapped[str] = mapped_column(String(50), nullable=False)
    version_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    rows: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    overhead_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0")
    )
    transport_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0")
    )
    contingency_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0")
    )
    # True = версия использует свои %, не глобальные настройки задачи
    expenses_overridden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    optimization_proposals: Mapped[Optional[List]] = mapped_column(JSON, nullable=True)
    # True = версия откатана, скрыта в UI, но не удалена из БД
    is_rolled_back: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # 'result' для result-файлов, 'input' для input-файлов
    file_slot: Mapped[str] = mapped_column(String(20), nullable=False, default="result")
    # Тип задачи — для generic-режима редактора без JOIN
    task_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # --- Единый редактор (план 2026-08-02) ---
    # Черновик: правки автосохраняются сюда и не влияют ни на rows, ни на файл,
    # пока пользователь не нажал «Применить».
    draft_rows: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    draft_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    draft_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Счётчик применённых изменений. Клиент присылает свой rev при «Применить»;
    # расхождение = кто-то сохранил раньше → 409 вместо тихого затирания.
    rev: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Обратимый коэффициент к ценам: {"work": 1.01, "material": 1.0,
    #  "scope": "all" | ["row_id", ...]}. Исходные цены в rows не меняются.
    coefficient: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

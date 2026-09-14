"""Правило для промпта, выученное из правок и включённое человеком.

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 8.

Правило меняет поведение расчёта во всех будущих сметах и при этом невидимо в
результате — в отличие от цены, которую видно в строке. Поэтому создаёт и
включает его только менеджер, а в промпт уходят лишь включённые правила
(правило 9 CLAUDE.md: молча система на своих данных не учится).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Область «на все стадии конвейера».
SCOPE_ALL = "ALL"


class PromptRule(Base):
    __tablename__ = "prompt_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # ALL либо тип задачи (LIST_FROM_GRAND, ESTIMATE_FROM_LIST, …).
    scope: Mapped[str] = mapped_column(String(50), nullable=False, default=SCOPE_ALL)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # Кто и когда включил: правило невидимо в результате, поэтому подпись обязательна.
    enabled_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    enabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )


__all__ = ["PromptRule", "SCOPE_ALL"]

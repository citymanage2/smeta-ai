"""Запрос КП у отдела производства работ (план 2026-09-14-zapros-kp.md).

Запрос — отдельная сущность, а не задача ИИ (`tasks`): у задачи `pending` значит
«в очереди», статусы кормят ETA и метрики, а исполнителя, позиций и вложений у
неё нет. Модель — как в закупочных системах: «запрос → позиции-снимки → КП →
цены матрицей «позиция × КП»».

* Запрос адресован **роли** целиком (`target_role`), а не человеку: все
  сотрудники роли видят его одновременно, `taken_by_id` — только подпись «кто
  взял».
* Позиции — **снимок** на момент отправки. `row_id` между стадиями не стабилен,
  а поставщику отправлено конкретное; правка документа запрос не меняет.
* Приведённая цена (без НДС, в единице позиции) **не хранится** — считается на
  лету, как отклонение от цели сводной (правило №16).

Файлы (вложения автора и сами КП) лежат в S3 под префиксом `kp/{request_id}/`,
в БД — только метаданные и `storage_key`; наружу ключ не отдаётся.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy import JSON as _JSON
from sqlalchemy.dialects.postgresql import JSONB as _JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# JSONB на PostgreSQL, JSON на SQLite (тесты) — как в models/job.py
JSONB = _JSON().with_variant(_JSONB(), "postgresql")

# --- Статусы запроса ---
STATUS_NEW = "new"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"
STATUSES = (STATUS_NEW, STATUS_IN_PROGRESS, STATUS_DONE, STATUS_CANCELLED)

# --- Категория позиций запроса ---
CATEGORY_MATERIAL = "material"
CATEGORY_WORK = "work"
CATEGORIES = (CATEGORY_MATERIAL, CATEGORY_WORK)

# Стадии, с которых ставится запрос. Раздел сводной — нет (не входит в функцию).
SOURCE_KINDS = ("list", "completeness", "estimate", "optimization")


def _uuid_pk() -> Mapped[str]:
    return mapped_column(
        PG_UUID(as_uuid=False), primary_key=True, default=lambda: str(_uuid.uuid4())
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


class KpRequest(Base):
    __tablename__ = "kp_requests"
    __table_args__ = (
        Index("ix_kp_requests_role_status", "target_role", "status"),
    )

    id: Mapped[str] = _uuid_pk()
    project_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    card_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), ForeignKey("workflow_cards.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # list | completeness | estimate | optimization
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    source_task_id: Mapped[Optional[str]] = mapped_column(PG_UUID(as_uuid=False), nullable=True)
    source_version_id: Mapped[Optional[str]] = mapped_column(PG_UUID(as_uuid=False), nullable=True)
    # material | work
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    # supply_manager | contractor_manager — кому адресован (роль целиком)
    target_role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_NEW)

    author_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    taken_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    taken_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    author_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Запись цен в прайс при завершении (фаза 7): done | failed
    pricelist_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    pricelist_summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    pricelist_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pricelist_written_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Применение в оптимизации (фаза 8)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_version_id: Mapped[Optional[str]] = mapped_column(PG_UUID(as_uuid=False), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class KpRequestFile(Base):
    """Вложение автора запроса: спецификация, ТЗ, чертёж."""

    __tablename__ = "kp_request_files"

    id: Mapped[str] = _uuid_pk()
    request_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), ForeignKey("kp_requests.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class KpOffer(Base):
    """Коммерческое предложение поставщика или подрядчика (файл + условия)."""

    __tablename__ = "kp_offers"

    id: Mapped[str] = _uuid_pk()
    request_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), ForeignKey("kp_requests.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    supplier_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    offer_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # with_vat | without_vat
    vat_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="without_vat")
    # Ставка при with_vat; по умолчанию 22 %
    vat_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 2, asdecimal=False), nullable=True)
    # Только для запросов по работам: цена работы включает материалы
    includes_materials: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    storage_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # queued | processing | parsed | failed
    parse_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    parse_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parse_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    parse_cost: Mapped[Optional[float]] = mapped_column(Numeric(asdecimal=False), nullable=True)
    # Подсказки разбора (фаза 6, миграция 053): догадки ИИ, которые не заполняют
    # поле сами — {vat_mode, vat_rate, includes_materials, prices_found,
    # dropped_unknown}. Условия КП задаёт человек.
    parse_hints: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class KpRequestItem(Base):
    """Позиция запроса — снимок строк документа на момент отправки."""

    __tablename__ = "kp_request_items"

    id: Mapped[str] = _uuid_pk()
    request_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), ForeignKey("kp_requests.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # material | work
    item_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    qty: Mapped[Optional[float]] = mapped_column(Numeric(asdecimal=False), nullable=True)
    sheet: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Ключи строк документа, свёрнутых в эту позицию, в порядке документа
    source_row_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    selected_offer_id: Mapped[Optional[str]] = mapped_column(
        PG_UUID(as_uuid=False), ForeignKey("kp_offers.id", ondelete="SET NULL"),
        nullable=True,
    )


class KpOfferPrice(Base):
    """Цена позиции в КП — ячейка матрицы «позиция × КП»."""

    __tablename__ = "kp_offer_prices"
    __table_args__ = (
        UniqueConstraint("offer_id", "item_id", name="uq_kp_offer_prices_offer_item"),
    )

    id: Mapped[str] = _uuid_pk()
    offer_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), ForeignKey("kp_offers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    item_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=False), ForeignKey("kp_request_items.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # За единицу КП, как в файле (с НДС или без — по условиям КП)
    price: Mapped[float] = mapped_column(Numeric(asdecimal=False), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name_in_offer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # NULL = как у КП
    includes_materials: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # ai | manual
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="manual")
    confidence: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


__all__ = [
    "KpRequest", "KpRequestFile", "KpOffer", "KpRequestItem", "KpOfferPrice",
    "STATUS_NEW", "STATUS_IN_PROGRESS", "STATUS_DONE", "STATUS_CANCELLED", "STATUSES",
    "CATEGORY_MATERIAL", "CATEGORY_WORK", "CATEGORIES", "SOURCE_KINDS",
]

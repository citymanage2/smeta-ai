"""HTTP-контракт запросов КП (план 2026-09-14-zapros-kp.md, фаза 2).

Ключ S3 (`storage_key`) в контракт не входит намеренно: файл скачивается только
через роутер с проверкой роли (проблема 18 плана).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["material", "work"]


# --- Вход -------------------------------------------------------------------

class KpPreviewRequest(BaseModel):
    card_id: str
    kind: str
    version_id: Optional[str] = None
    row_ids: list[str] = Field(default_factory=list)


class KpGroupIn(BaseModel):
    category: Category
    row_ids: list[str] = Field(default_factory=list)


class KpCreatePayload(BaseModel):
    """JSON-часть multipart-запроса `POST /kp-requests` (поле `payload`)."""

    card_id: str
    kind: str
    version_id: Optional[str] = None
    author_comment: Optional[str] = Field(default=None, max_length=10000)
    groups: list[KpGroupIn] = Field(default_factory=list)


# --- Выход ------------------------------------------------------------------

class KpItemOut(BaseModel):
    """Позиция запроса (в предпросмотре — ещё не сохранённая, без id)."""

    id: Optional[str] = None
    position: int = 0
    item_type: Optional[str] = None
    name: str
    unit: Optional[str] = None
    qty: Optional[float] = None
    sheet: Optional[str] = None
    source_no: Optional[str] = None
    source_row_ids: list[str] = Field(default_factory=list)
    selected_offer_id: Optional[str] = None


class KpPreviewGroup(BaseModel):
    category: str
    target_role: Optional[str] = None
    # Активных сотрудников роли; 0 — группу отправить нельзя
    employees: Optional[int] = None
    items: list[KpItemOut] = Field(default_factory=list)


class KpPreviewGroups(BaseModel):
    material: KpPreviewGroup
    work: KpPreviewGroup
    unknown: KpPreviewGroup


class KpPreviewResponse(BaseModel):
    version_id: str
    groups: KpPreviewGroups
    # Разделы и строки без наименования — в запрос не попадают
    skipped: int = 0
    # Выделенные строки, которых уже нет в сохранённом документе
    missing_row_ids: list[str] = Field(default_factory=list)


class KpFileOut(BaseModel):
    id: str
    file_name: str
    mime_type: str
    size_bytes: int
    uploaded_by: Optional[int] = None
    uploaded_by_name: Optional[str] = None
    created_at: datetime


class KpRequestBrief(BaseModel):
    id: str
    project_id: str
    project_name: Optional[str] = None
    card_id: str
    card_name: Optional[str] = None
    source_kind: str
    category: str
    target_role: str
    status: str
    author_id: Optional[int] = None
    author_name: Optional[str] = None
    author_comment: Optional[str] = None
    taken_by_id: Optional[int] = None
    taken_by_name: Optional[str] = None
    taken_at: Optional[datetime] = None
    completed_by_id: Optional[int] = None
    completed_by_name: Optional[str] = None
    completed_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None
    items_count: int = 0
    files_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None


class KpPermissionsOut(BaseModel):
    """Что текущий пользователь может сделать с запросом — решает сервер."""

    can_work: bool
    can_manage: bool
    can_edit_files: bool


class KpRequestDetail(KpRequestBrief):
    source_task_id: Optional[str] = None
    source_version_id: Optional[str] = None
    report: Optional[str] = None
    pricelist_status: Optional[str] = None
    pricelist_summary: Optional[dict] = None
    pricelist_error: Optional[str] = None
    pricelist_written_at: Optional[datetime] = None
    applied_version_id: Optional[str] = None
    items: list[KpItemOut] = Field(default_factory=list)
    files: list[KpFileOut] = Field(default_factory=list)
    permissions: KpPermissionsOut


class KpCreateResponse(BaseModel):
    requests: list[KpRequestBrief]


class KpFilesResponse(BaseModel):
    files: list[KpFileOut]


class KpCountersResponse(BaseModel):
    # Новых запросов своей роли (производство); у продаж — 0
    new: int = 0
    # Завершённых, но не применённых запросов по карточкам (продажи)
    done_not_applied: dict[str, int] = Field(default_factory=dict)

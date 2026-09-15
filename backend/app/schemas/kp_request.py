"""HTTP-контракт запросов КП (план 2026-09-14-zapros-kp.md, фазы 2 и 4).

Ключ S3 (`storage_key`) в контракт не входит намеренно: файл скачивается только
через роутер с проверкой роли (проблема 18 плана).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional, Union

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
    # Фаза 4: загрузить/править/удалить КП и цены (сотрудник роли, до завершения)
    can_edit_offers: bool = False
    # Завершить запрос (сотрудник роли, новый или в работе)
    can_complete: bool = False
    # Отметить КП выбранным у позиции (производство — в работе; продажи — и после завершения)
    can_select_offer: bool = False


# --- КП и цены (фаза 4) -----------------------------------------------------

class KpOfferOut(BaseModel):
    id: str
    supplier_name: str = ""
    offer_date: Optional[date] = None
    vat_mode: str
    vat_rate: Optional[float] = None
    includes_materials: bool = False
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    has_file: bool = False
    parse_status: Optional[str] = None
    parse_error: Optional[str] = None
    parse_started_at: Optional[datetime] = None
    parse_hints: Optional[dict] = None
    created_by: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: datetime


class KpOfferPatch(BaseModel):
    """Частичная правка условий КП — применяются только переданные поля."""

    supplier_name: Optional[str] = Field(default=None, max_length=500)
    offer_date: Optional[date] = None
    vat_mode: Optional[Literal["with_vat", "without_vat"]] = None
    vat_rate: Optional[float] = None
    includes_materials: Optional[bool] = None


class KpPriceIn(BaseModel):
    price: float = Field(gt=0)
    unit: Optional[str] = Field(default=None, max_length=64)
    # None — как у КП
    includes_materials: Optional[bool] = None


class KpCellOut(BaseModel):
    """Ячейка матрицы «позиция × КП»: цена в единице КП и приведённая."""

    offer_id: str
    item_id: Optional[str] = None
    price: Optional[float] = None
    unit: Optional[str] = None
    name_in_offer: Optional[str] = None
    source: Optional[str] = None
    confidence: Optional[str] = None
    confirmed: Optional[bool] = None
    includes_materials: bool = False
    # Без НДС, за единицу позиции; None — цены нет или единица не сводится
    normalized_price: Optional[float] = None
    unit_status: Optional[str] = None
    reason: Optional[str] = None


class KpBestOut(BaseModel):
    """Итоговая цена позиции: выбранное КП, иначе минимум подтверждённых."""

    offer_id: str
    supplier_name: str = ""
    offer_date: Optional[date] = None
    price: float
    includes_materials: bool = False
    selected: bool = False
    offers_count: int = 0


class KpItemDetailOut(KpItemOut):
    cells: list[KpCellOut] = Field(default_factory=list)
    min_offer_id: Optional[str] = None
    best: Optional[KpBestOut] = None


class KpSelectOfferIn(BaseModel):
    offer_id: Optional[str] = None


class KpCompleteIn(BaseModel):
    report: Optional[str] = Field(default=None, max_length=20000)


class KpRequestDetail(KpRequestBrief):
    source_task_id: Optional[str] = None
    source_version_id: Optional[str] = None
    report: Optional[str] = None
    pricelist_status: Optional[str] = None
    pricelist_summary: Optional[dict] = None
    pricelist_error: Optional[str] = None
    pricelist_written_at: Optional[datetime] = None
    applied_version_id: Optional[str] = None
    items: list[KpItemDetailOut] = Field(default_factory=list)
    files: list[KpFileOut] = Field(default_factory=list)
    offers: list[KpOfferOut] = Field(default_factory=list)
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


# --- Цены из КП в оптимизацию (фаза 8) ---------------------------------------

class KpApplyPreviewIn(BaseModel):
    card_id: str
    version_id: str


class KpApplyIn(BaseModel):
    card_id: str
    version_id: str
    client_rev: int
    preview_hash: str
    # item_id → id строки / список id / null (пропустить) — только для «Неоднозначно»
    choices: dict[str, Optional[Union[str, list[str]]]] = Field(default_factory=dict)


class KpApplyRowOut(BaseModel):
    row_id: str
    name: Optional[str] = None
    unit: Optional[str] = None
    sheet: Optional[str] = None
    source_no: Optional[str] = None
    type: Optional[str] = None
    field: str
    old_price: Any = None
    new_price: float
    request_id: str
    item_id: str
    offer_id: str
    supplier: Optional[str] = None
    offer_date: Optional[str] = None
    offers_count: int
    includes_materials: bool
    match: str


class KpApplyCandidateOut(BaseModel):
    row_id: str
    name: Optional[str] = None
    unit: Optional[str] = None
    sheet: Optional[str] = None
    source_no: Optional[str] = None
    qty: Any = None
    old_price: Any = None
    new_price: float


class KpApplyItemOut(BaseModel):
    request_id: str
    item_id: str
    item_type: str
    name: str
    unit: Optional[str] = None
    sheet: Optional[str] = None
    source_no: Optional[str] = None
    price: float
    supplier: Optional[str] = None
    offer_date: Optional[str] = None
    offers_count: int
    includes_materials: bool
    candidates: list[KpApplyCandidateOut] = Field(default_factory=list)


class KpApplySkippedOut(BaseModel):
    row_id: str
    item_id: str
    name: Optional[str] = None
    reason: str


class KpApplyPreviewOut(BaseModel):
    version_id: str
    rev: int
    preview_hash: str
    rows: list[KpApplyRowOut]
    ambiguous: list[KpApplyItemOut]
    not_found: list[KpApplyItemOut]
    skipped: list[KpApplySkippedOut]
    no_price_count: int
    includes_materials_count: int


class KpApplyOut(BaseModel):
    version_id: str
    version_number: int
    source_version_id: str
    applied_rows: int
    changes_count: int
    request_ids: list[str]

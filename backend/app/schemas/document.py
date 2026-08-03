"""Контракт единого редактора документов.

Один и тот же контракт для всех типов документов; чем они отличаются, описывает
`row_format` (формат строки) и набор разрешённых действий на клиенте.
"""
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

RowFormat = Literal["generic", "estimate"]
ReadonlyReason = Literal["no_permission", "task_processing", "input_readonly"]


class VersionBrief(BaseModel):
    id: str
    version_number: int
    version_label: str
    version_display_name: str
    is_rolled_back: bool
    created_at: str
    # Проценты доп. расходов у каждой версии свои: сравнение версий без них
    # посчитало бы разные версии по одной ставке и показало неверную выгоду.
    overhead_pct: float = 0.0
    transport_pct: float = 0.0
    contingency_pct: float = 0.0
    expenses_overridden: bool = False


class LockInfo(BaseModel):
    user_id: Optional[int]
    user_name: str
    heartbeat_at: str


class ProjectSettings(BaseModel):
    """Проценты доп. расходов проекта — единый источник вместо трёх хардкодов."""
    overhead_pct: Decimal
    transport_pct: Decimal
    # Имя проекта показывается в шапке выгрузки-ведомости.
    name: str = ""


class SectionDivergence(BaseModel):
    """Раздел сводной и смета показывают разное — обе стороны в цифрах."""
    section_rows: int
    estimate_rows: int
    section_total: float
    estimate_total: float


class ResolveDivergenceRequest(BaseModel):
    # Чья сторона верна: 'section' — правки раздела, 'estimate' — строки сметы.
    prefer: str


class DocumentMeta(BaseModel):
    card_id: str
    kind: str
    row_format: RowFormat
    file_slot: str
    task_id: str
    task_type: str
    task_status: str
    can_write: bool
    readonly_reason: Optional[ReadonlyReason] = None
    rev: int
    active_version_id: Optional[str] = None
    versions: list[VersionBrief] = Field(default_factory=list)
    coefficient: Optional[dict] = None
    has_draft: bool = False
    draft_updated_at: Optional[str] = None
    lock: Optional[LockInfo] = None
    project: ProjectSettings
    # Только у раздела сводной и только пока стороны не сведены.
    divergence: Optional[SectionDivergence] = None


class DocumentRows(BaseModel):
    version_id: str
    rev: int
    rows: list[Any]
    draft_rows: Optional[list[Any]] = None


class SaveDraftRequest(BaseModel):
    version_id: Optional[str] = None
    rows: list[Any]


class ApplyRequest(BaseModel):
    version_id: Optional[str] = None
    # rev, на котором работал клиент. Расхождение → 409.
    rev: int
    # Если не передан — применяется черновик.
    rows: Optional[list[Any]] = None


class ApplyResponse(BaseModel):
    version_id: str
    rev: int
    rows_count: int
    changes_count: int


class CoefficientRequest(BaseModel):
    """Коэффициент к ценам документа.

    Ноль и минус запрещены на входе: они молча обнулили бы или перевернули
    смету, а замечено это было бы уже на тендере.
    """
    work: float = Field(default=1.0, gt=0, le=100)
    material: float = Field(default=1.0, gt=0, le=100)
    # "all" — весь документ; список — только эти строки (галочки в таблице).
    scope: Any = "all"


class ExportColumn(BaseModel):
    """Колонка выгрузки. Приходит от документа: у перечня свои, у сметы свои."""
    key: str
    label: str = ""
    numeric: bool = False


class ExportHeader(BaseModel):
    """Шапка ведомости. По умолчанию включено всё (решение пользователя 3.5)."""
    title: str = ""
    object_name: str = ""
    project_name: str = ""
    show_date: bool = True
    show_total: bool = True


class ExportRequest(BaseModel):
    columns: list[ExportColumn] = Field(default_factory=list)
    # Строки приходят из предпросмотра: человек мог их поправить или удалить.
    rows: list[dict] = Field(default_factory=list)
    header: ExportHeader = Field(default_factory=ExportHeader)
    sheet_name: str = "Выгрузка"
    file_name: Optional[str] = None


class PriceListItem(BaseModel):
    """Позиция документа, отправленная в прайс."""
    kind: str
    name: str
    unit: Optional[str] = None
    price: Optional[float] = None


class PriceListRequest(BaseModel):
    items: list[PriceListItem] = Field(default_factory=list)


class PriceListResponse(BaseModel):
    added: int
    updated: int
    skipped: int
    # Почему позиции пропущены — иначе «пропущено 4» ничего не объясняет.
    skipped_reasons: dict = Field(default_factory=dict)


class AnalogRowIn(BaseModel):
    """Позиция, отправленная на поиск аналогов."""
    row_id: str
    name: str
    unit: Optional[str] = None
    qty: Optional[float] = None
    price: Optional[float] = None
    kind: Optional[str] = None


class AnalogsStartRequest(BaseModel):
    rows: list[AnalogRowIn] = Field(default_factory=list)
    version_id: Optional[str] = None


class AnalogsStartResponse(BaseModel):
    run_id: str
    status: str
    total: int
    # Во что обойдётся запуск — человек видит это до подтверждения.
    estimate: dict = Field(default_factory=dict)


class AnalogsStateResponse(BaseModel):
    run_id: Optional[str] = None
    status: Optional[str] = None
    processed: int = 0
    total: int = 0
    results: list[dict] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: Optional[str] = None


class ChangeEntry(BaseModel):
    row_number: int
    row_id: Optional[str] = None
    row_name: str = ""
    field: str
    previous: Any = None
    new: Any = None


class HistoryEntryOut(BaseModel):
    id: str
    kind: Optional[str] = None
    operation_type: str
    description: str
    user_id: Optional[int] = None
    user_name: str = ""
    created_at: str
    changes_count: int = 0
    changes: list[ChangeEntry] = Field(default_factory=list)


class HeartbeatResponse(BaseModel):
    lock: Optional[LockInfo] = None

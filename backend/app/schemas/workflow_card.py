from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal

from app.schemas.eta import TaskEta



class InputFileBrief(BaseModel):
    name: str
    mime_type: str
    size_bytes: int


class TaskUsage(BaseModel):
    """Во что обошлась стадия и сколько она шла.

    Токены — сумма input + output + cache_read + cache_creation за все прогоны
    задачи. Время — только последнего прогона: перезапуск переставляет
    started_at/finished_at, а потраченные деньги никуда не деваются.

    `extra_*` — доспросы ИИ по уже сформированному файлу стадии (цена строки,
    аналоги, шаги оптимизации). Отдельной цифрой, потому что именно по разнице
    видно, где утекают деньги.
    """

    tokens: int = 0
    cost_usd: float = 0.0
    extra_tokens: int = 0
    extra_cost_usd: float = 0.0
    queue_seconds: Optional[float] = None
    work_seconds: Optional[float] = None
    queue_running: bool = False
    work_running: bool = False


class TaskBrief(BaseModel):
    id: str
    task_type: str
    status: str
    name: Optional[str]
    created_at: str
    input_files: list[InputFileBrief] = []
    progress_message: Optional[str] = None
    # Причина падения задачи. Едет вместе со статусом: «Ошибка» без объяснения
    # заставляет открывать смету ради одной строки, а иногда и не заставляет —
    # человек просто жмёт «Повторить» и получает ту же ошибку.
    error_message: Optional[str] = None
    # Сумма сформированной сметы в рублях (task.cost). Не путать с cost_usd
    # в usage — то стоимость запросов к ИИ, это деньги заказчика.
    cost: Optional[float] = None
    # Затраты и тайминги стадии. None — метрики не считались (одиночный ответ).
    usage: Optional[TaskUsage] = None
    # Выжимка прогресса по белому списку (счётчики «N из M»), без чувствительных
    # полей progress_data. Заполняется через build_progress_summary().
    progress_data: Optional[dict] = None
    # Прогноз старта и готовности — только у активных задач (см. eta_service).
    eta: Optional[TaskEta] = None

    model_config = {"from_attributes": True}


class WorkflowCardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    stage: Literal["list", "completeness", "estimate", "optimization"] = "list"

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> str:
        v = str(v).strip()
        if not v:
            raise ValueError("name cannot be empty or whitespace")
        return v


class WorkflowCardUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    stage: Optional[Literal["list", "completeness", "estimate", "optimization"]] = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: object) -> Optional[str]:
        if v is None:
            return v
        v = str(v).strip()
        if not v:
            raise ValueError("name cannot be empty or whitespace")
        return v


# ---------------------------------------------------------------------------
# Card Detail — rich per-stage file metadata
# ---------------------------------------------------------------------------

class InputFileDetail(BaseModel):
    index: int
    name: str
    size_bytes: int
    mime_type: str


class ResultFileDetail(BaseModel):
    result_id: int
    slot: str
    file_name: str
    size_bytes: int
    mime_type: str
    created_at: str


class StageDetail(BaseModel):
    task_id: str
    task_type: str
    task_status: str
    task_name: Optional[str]
    task_created_at: str
    manually_edited_at: Optional[str]
    input_files: list[InputFileDetail] = []
    result_files: list[ResultFileDetail] = []


class CardDetailResponse(BaseModel):
    id: str
    project_id: str
    name: str
    stage: str
    source_stage: Optional[StageDetail]
    completeness_stage: Optional[StageDetail]
    estimate_stage: Optional[StageDetail]
    optimization_stage: Optional[StageDetail]


class WorkflowCardResponse(BaseModel):
    id: str
    project_id: str
    name: str
    stage: str
    list_task_id: Optional[str]
    completeness_task_id: Optional[str]
    estimate_task_id: Optional[str]
    optimization_task_id: Optional[str]
    primary_version_id: Optional[str] = None
    list_task: Optional[TaskBrief]
    completeness_task: Optional[TaskBrief]
    estimate_task: Optional[TaskBrief]
    optimization_task: Optional[TaskBrief]
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

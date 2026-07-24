from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal



class InputFileBrief(BaseModel):
    name: str
    mime_type: str
    size_bytes: int


class TaskBrief(BaseModel):
    id: str
    task_type: str
    status: str
    name: Optional[str]
    created_at: str
    input_files: list[InputFileBrief] = []
    progress_message: Optional[str] = None
    # Выжимка прогресса по белому списку (счётчики «N из M»), без чувствительных
    # полей progress_data. Заполняется через build_progress_summary().
    progress_data: Optional[dict] = None

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

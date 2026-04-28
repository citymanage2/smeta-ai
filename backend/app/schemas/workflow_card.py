from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from uuid import UUID
from datetime import datetime


class TaskBrief(BaseModel):
    id: str
    task_type: str
    status: str
    name: Optional[str]
    created_at: str

    model_config = {"from_attributes": True}


class WorkflowCardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)

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


class WorkflowCardResponse(BaseModel):
    id: str
    project_id: str
    name: str
    stage: str
    list_task_id: Optional[str]
    completeness_task_id: Optional[str]
    estimate_task_id: Optional[str]
    optimization_task_id: Optional[str]
    list_task: Optional[TaskBrief]
    completeness_task: Optional[TaskBrief]
    estimate_task: Optional[TaskBrief]
    optimization_task: Optional[TaskBrief]
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

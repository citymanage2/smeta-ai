from __future__ import annotations
from decimal import Decimal
from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid as _uuid


class EstimateRowSchema(BaseModel):
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    # Стабильный идентификатор строки сквозь все версии; при первичном парсинге = id
    lineage_id: str
    num: Optional[int] = None
    type: Literal["work", "material", "section"] = "work"
    name: str
    unit: str = ""
    qty: Optional[float] = None
    price_work: Optional[float] = None
    price_material: Optional[float] = None
    cost: Optional[float] = None
    selected: bool = False
    abc_group: Optional[Literal["A", "B", "C"]] = None
    optimization_note: Optional[str] = None
    optimization_confidence: Optional[Literal["high", "medium", "low"]] = None
    is_excluded: Optional[bool] = None


class OptimizationProposalSchema(BaseModel):
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    row_id: Optional[str] = None
    proposal_type: Literal["add", "remove", "replace_tech", "replace_material", "price_search"]
    description: str
    explanation: str
    economy_rub: Optional[float] = None
    confidence: Literal["high", "medium", "low"]
    source: Optional[str] = None
    new_value: Optional[dict] = None


class EstimateVersionCreate(BaseModel):
    task_id: str
    version_number: int
    version_label: Literal[
        "original",
        "client",
        "completeness_checked",
        "no_redundant",
        "tech_optimized",
        "material_optimized",
        "custom",
    ]
    version_display_name: str
    rows: list[EstimateRowSchema] = []
    overhead_pct: Decimal = Decimal("0")
    transport_pct: Decimal = Decimal("0")
    contingency_pct: Decimal = Decimal("0")
    expenses_overridden: bool = False
    optimization_proposals: Optional[list[OptimizationProposalSchema]] = None


class EstimateVersionSummary(BaseModel):
    id: str
    task_id: str
    version_number: int
    version_label: str
    version_display_name: str
    overhead_pct: Decimal
    transport_pct: Decimal
    contingency_pct: Decimal
    expenses_overridden: bool
    is_rolled_back: bool
    created_at: str

    model_config = {"from_attributes": True}


class EstimateVersionResponse(BaseModel):
    id: str
    task_id: str
    version_number: int
    version_label: str
    version_display_name: str
    rows: list[EstimateRowSchema]
    overhead_pct: Decimal
    transport_pct: Decimal
    contingency_pct: Decimal
    expenses_overridden: bool
    optimization_proposals: Optional[list[OptimizationProposalSchema]] = None
    is_rolled_back: bool
    created_at: str

    model_config = {"from_attributes": True}

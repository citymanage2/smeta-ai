from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class SummaryOverrides(BaseModel):
    transport_pct: Decimal = Field(default=Decimal("1.0"))
    cleanup_pct: Decimal = Field(default=Decimal("1.5"))
    overhead_pct: Decimal = Field(default=Decimal("2.0"))
    daily_workers_cost: Decimal = Field(default=Decimal("0"))
    bank_guarantee_cost: Decimal = Field(default=Decimal("0"))
    cleaning_cost: Decimal = Field(default=Decimal("0"))
    ppr_cost: Decimal = Field(default=Decimal("0"))
    commissioning_cost: Decimal = Field(default=Decimal("0"))
    contingency_pct: Decimal = Field(default=Decimal("2.0"))
    profit_pct: Decimal = Field(default=Decimal("16.0"))
    vat_works_pct: Decimal = Field(default=Decimal("22.0"))
    vat_materials_pct: Decimal = Field(default=Decimal("20.0"))
    tax_pct: Decimal = Field(default=Decimal("3.0"))


class SectionInput(BaseModel):
    """Элемент списка разделов при создании/обновлении сводной."""
    card_id: str
    version_id: str


class SummaryEstimateCreate(BaseModel):
    sections: list[SectionInput]
    overrides: Optional[SummaryOverrides] = None


class SummaryEstimateUpdate(BaseModel):
    # sections — полный снэпшот строк после редактирования в UI
    sections: Optional[list[Any]] = None
    overrides: Optional[SummaryOverrides] = None
    total_for_customer: Optional[Decimal] = None


class SummaryEstimateResponse(BaseModel):
    id: str
    project_id: str
    sections: list[Any]
    overrides: dict[str, Any]
    total_for_customer: Decimal
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

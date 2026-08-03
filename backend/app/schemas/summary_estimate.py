from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class SummaryOverrides(BaseModel):
    coefficient: Decimal = Field(default=Decimal("1.0"))
    transport_pct: Decimal = Field(default=Decimal("3.0"))
    cleanup_pct: Decimal = Field(default=Decimal("3.0"))
    overhead_pct: Decimal = Field(default=Decimal("3.0"))
    daily_workers_cost: Decimal = Field(default=Decimal("0"))      # stores COUNT of workers
    bank_guarantee_cost: Decimal = Field(default=Decimal("0"))     # stored as без НДС
    cleaning_cost: Decimal = Field(default=Decimal("0"))
    ppr_cost: Decimal = Field(default=Decimal("0"))
    commissioning_cost: Decimal = Field(default=Decimal("0"))      # row 10: Разнорабочие мусор
    construction_control_cost: Decimal = Field(default=Decimal("0"))
    author_supervision_cost: Decimal = Field(default=Decimal("0"))
    passes_cost: Decimal = Field(default=Decimal("0"))
    site_office_cost: Decimal = Field(default=Decimal("0"))
    travel_cost: Decimal = Field(default=Decimal("0"))
    rp_cost: Decimal = Field(default=Decimal("0"))
    housing_rent_cost: Decimal = Field(default=Decimal("0"))
    workers_transport_cost: Decimal = Field(default=Decimal("0"))
    contingency_pct: Decimal = Field(default=Decimal("2.0"))
    profit_pct: Decimal = Field(default=Decimal("20.0"))
    vat_full_cost_pct: Decimal = Field(default=Decimal("22.0"))
    tax_pct: Decimal = Field(default=Decimal("2.0"))
    # row management
    hidden_fixed_rows: list[str] = Field(default_factory=list)
    custom_rows_before: list[dict] = Field(default_factory=list)
    custom_rows_after: list[dict] = Field(default_factory=list)
    # legacy fields kept for backward compatibility (not used in new calc)
    vat_works_pct: Optional[Decimal] = Field(default=None)
    vat_materials_pct: Optional[Decimal] = Field(default=None)


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

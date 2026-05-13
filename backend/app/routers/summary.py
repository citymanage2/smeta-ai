"""API endpoints for SummaryEstimate."""
import io

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.project import Project
from app.schemas.summary_estimate import (
    CustomExportRequest,
    SummaryEstimateCreate,
    SummaryEstimateResponse,
    SummaryEstimateUpdate,
    SummaryOverrides,
)
from app.services import summary_service
from app.utils.auth import get_current_user
from app.utils.xlsx_summary import generate_custom_export_xlsx, generate_summary_xlsx

logger = structlog.get_logger()

router = APIRouter(tags=["summary"])


async def _project_or_404(project_id: str, db: AsyncSession) -> Project:
    proj = await db.get(Project, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return proj


@router.get("/projects/{project_id}/summary", response_model=SummaryEstimateResponse)
async def get_summary(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _project_or_404(project_id, db)
    summary = await summary_service.get_summary(project_id, db)
    if summary is None:
        raise HTTPException(status_code=404, detail="Сводная смета не найдена")
    return summary


@router.post("/projects/{project_id}/summary", response_model=SummaryEstimateResponse, status_code=201)
async def create_summary(
    project_id: str,
    body: SummaryEstimateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _project_or_404(project_id, db)
    existing = await summary_service.get_summary(project_id, db)
    if existing is not None:
        preserved_overrides = body.overrides or SummaryOverrides(**existing.overrides)
        await db.delete(existing)
        await db.commit()
        body = SummaryEstimateCreate(sections=body.sections, overrides=preserved_overrides)
    return await summary_service.create_summary(project_id, body, db)


@router.put("/projects/{project_id}/summary", response_model=SummaryEstimateResponse)
async def update_summary(
    project_id: str,
    body: SummaryEstimateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _project_or_404(project_id, db)
    summary = await summary_service.get_summary(project_id, db)
    if summary is None:
        raise HTTPException(status_code=404, detail="Сводная смета не найдена")
    return await summary_service.update_summary(summary, body, db)


@router.get("/projects/{project_id}/summary/export")
async def export_summary(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _project_or_404(project_id, db)
    summary = await summary_service.get_summary(project_id, db)
    if summary is None:
        raise HTTPException(status_code=404, detail="Сводная смета не найдена")

    xlsx_bytes = generate_summary_xlsx(summary)
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=summary_{project_id}.xlsx"},
    )


@router.post("/projects/{project_id}/summary/custom-export")
async def custom_export_summary(
    project_id: str,
    body: CustomExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _project_or_404(project_id, db)

    flat_rows: list[dict] = []
    section_groups: list[tuple[str, list[dict]]] = []

    for row in body.rows:
        flat_rows.append({
            "section": row.section_name or "",
            "num": row.num,
            "name": row.name,
            "unit": row.unit,
            "qty": row.qty,
            "price_work": row.price_work,
            "cost_work": row.cost_work,
            "price_material": row.price_material,
            "cost_material": row.cost_material,
        })

    # Группировка для многолистового вывода
    seen: dict[str, list[dict]] = {}
    for r in flat_rows:
        sec = r.get("section") or "Раздел"
        seen.setdefault(sec, []).append(r)
    section_groups = list(seen.items())

    xlsx_bytes = generate_custom_export_xlsx(
        rows=flat_rows,
        visible_columns=body.visible_columns,
        section_groups=section_groups,
    )

    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=export.xlsx"},
    )

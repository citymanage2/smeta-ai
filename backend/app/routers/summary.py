"""API endpoints for SummaryEstimate."""
import io

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.project import Project
from app.schemas.summary_estimate import (
    SummaryEstimateCreate,
    SummaryEstimateResponse,
    SummaryEstimateUpdate,
)
from app.services import summary_service
from app.utils.auth import get_current_user
from app.utils.xlsx_summary import generate_summary_xlsx

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
        raise HTTPException(
            status_code=409,
            detail="Сводная смета уже существует. Используйте PUT для обновления.",
        )
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

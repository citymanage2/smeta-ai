"""API endpoints for SummaryEstimate."""
import asyncio
import io
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.project import Project
from app.schemas.document import ExportRequest
from app.schemas.summary_estimate import (
    SummaryEstimateCreate,
    SummaryEstimateResponse,
    SummaryEstimateUpdate,
    SummaryOverrides,
)
from app.services import summary_service
from app.utils.auth import get_current_user
from app.utils.permissions import can_access
from app.utils.xlsx_statement import generate_statement_xlsx
from app.utils.xlsx_summary import generate_summary_xlsx

logger = structlog.get_logger()

router = APIRouter(tags=["summary"])


async def _project_or_404(project_id: str, db: AsyncSession, current_user: dict) -> Project:
    proj = await db.get(Project, project_id)
    if proj is None or not can_access(proj.owner_id, current_user, proj.is_shared):
        raise HTTPException(status_code=404, detail="Проект не найден")
    return proj


@router.get("/projects/{project_id}/summary", response_model=SummaryEstimateResponse)
async def get_summary(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _project_or_404(project_id, db, current_user)
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
    await _project_or_404(project_id, db, current_user)
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
    await _project_or_404(project_id, db, current_user)
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
    await _project_or_404(project_id, db, current_user)
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
    body: ExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Выгрузка-ведомость по сводной.

    Тот же генератор, что у остальных документов (Фаза 9): столбцы и строки
    приходят из предпросмотра, шапка настраивается. У сводной есть свой фильтр
    «Разделы» — он применяется на клиенте, сюда строки приходят уже отобранными.
    """
    project = await _project_or_404(project_id, db, current_user)
    if not body.rows:
        raise HTTPException(status_code=422, detail="Нечего выгружать: не осталось ни одной строки")
    if not body.columns:
        raise HTTPException(status_code=422, detail="Выберите хотя бы один столбец")

    xlsx_bytes = await asyncio.to_thread(
        generate_statement_xlsx,
        [column.model_dump() for column in body.columns],
        body.rows,
        title=body.header.title,
        object_name=body.header.object_name,
        project_name=body.header.project_name or project.name,
        show_date=body.header.show_date,
        show_total=body.header.show_total,
        sheet_name=body.sheet_name,
    )

    ascii_name = "statement.xlsx"
    utf8_name = quote(body.file_name or f"{body.header.title or 'Выгрузка'}.xlsx", safe="")
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition":
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}",
        },
    )

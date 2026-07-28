from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import asyncio
import io
import structlog

from app.database import get_db
from app.models.result import TaskResult
from app.models.task import Task
from app.utils.auth import get_current_user
from app.utils.permissions import can_access
from app.services.excel_service import generate_list
from app.services import storage_service

logger = structlog.get_logger()

_REGENERABLE_TYPES = {
    "LIST_FROM_GRAND",
    "CHECK_LIST_COMPLETENESS",
    "CHECK_PROJECT_COMPLETENESS",
}

router = APIRouter(tags=["results"])


class ResultItem(BaseModel):
    file_id: int
    file_name: str
    mime_type: str
    slot: str = "result"


@router.get("/tasks/{task_id}/results", response_model=list[ResultItem])
async def list_task_results(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List all result files for a task."""
    # Verify task exists
    task_result = await db.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task or not can_access(task.owner_id, current_user, task.is_shared):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задача не найдена",
        )

    results = await db.execute(
        select(TaskResult).where(TaskResult.task_id == task_id)
    )
    files = results.scalars().all()

    has_estimate = any(f.slot == "estimate" for f in files)
    visible = [
        f for f in files
        if f.slot != "result" or not has_estimate
    ]

    return [
        ResultItem(
            file_id=f.id,
            file_name=f.file_name,
            mime_type=f.mime_type,
            slot=f.slot,
        )
        for f in visible
    ]


@router.post("/tasks/{task_id}/results/regenerate", response_model=ResultItem)
async def regenerate_task_result(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Regenerate the Excel result for a completed LIST/CHECK task from saved progress_data."""
    task_res = await db.execute(select(Task).where(Task.id == task_id))
    task = task_res.scalar_one_or_none()
    if not task or not can_access(task.owner_id, current_user, task.is_shared):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    task_type = (task.task_type or "").upper()
    if task_type not in _REGENERABLE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Перегенерация не поддерживается для типа задачи {task_type}",
        )

    progress = task.progress_data or {}
    items = progress.get("items", [])
    if not items:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="В задаче нет сохранённых позиций")

    summaries = progress.get("summaries", [])
    changes_summary: Optional[str] = "\n\n".join(summaries) if summaries else None

    # CPU-тяжёлая генерация xlsx — в отдельный поток, чтобы не морозить event loop
    # (иначе на время сериализации книги встают все HTTP-запросы единственного воркера).
    new_bytes = await asyncio.to_thread(generate_list, items, changes_summary=changes_summary)

    # Find existing result record (slot='result'), update its bytes; create if missing
    existing_res = await db.execute(
        select(TaskResult)
        .where(TaskResult.task_id == task_id, TaskResult.slot == "result")
        .order_by(TaskResult.created_at.desc())
    )
    existing = existing_res.scalar_one_or_none()

    _mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if existing:
        existing.storage_key = await storage_service.store_result_file(
            task_id, "result", existing.file_name or "Перечень.xlsx",
            existing.mime_type or _mime, new_bytes
        )
        await db.commit()
        await db.refresh(existing)
        return ResultItem(file_id=existing.id, file_name=existing.file_name, mime_type=existing.mime_type)

    # No result record yet — create one with a generic name
    storage_key = await storage_service.store_result_file(
        task_id, "result", "Перечень.xlsx", _mime, new_bytes
    )
    new_record = TaskResult(
        task_id=task_id,
        file_name="Перечень.xlsx",
        mime_type=_mime,
        storage_key=storage_key,
        size_bytes=len(new_bytes),
        slot="result",
    )
    db.add(new_record)
    await db.commit()
    await db.refresh(new_record)
    return ResultItem(file_id=new_record.id, file_name=new_record.file_name, mime_type=new_record.mime_type)


@router.get("/results/{file_id}/download")
async def download_result(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Download a result file by ID."""
    result = await db.execute(
        select(TaskResult).where(TaskResult.id == file_id)
    )
    file_record = result.scalar_one_or_none()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл не найден",
        )

    # Изоляция: файл доступен только владельцу задачи (или менеджеру).
    task = (
        await db.execute(select(Task).where(Task.id == file_record.task_id))
    ).scalar_one_or_none()
    if not task or not can_access(task.owner_id, current_user, task.is_shared):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл не найден",
        )

    data = await storage_service.load_bytes(file_record.storage_key)
    file_stream = io.BytesIO(data)
    filename = file_record.file_name

    # URL-encode filename for Content-Disposition
    import urllib.parse
    encoded_filename = urllib.parse.quote(filename)

    return StreamingResponse(
        file_stream,
        media_type=file_record.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Content-Length": str(len(data)),
        },
    )

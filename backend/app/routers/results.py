from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import io
import structlog

from app.database import get_db
from app.models.result import TaskResult
from app.models.task import Task
from app.utils.auth import get_current_user
from app.services.excel_service import generate_list

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
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задача не найдена",
        )

    results = await db.execute(
        select(TaskResult).where(TaskResult.task_id == task_id)
    )
    files = results.scalars().all()

    return [
        ResultItem(
            file_id=f.id,
            file_name=f.file_name,
            mime_type=f.mime_type,
        )
        for f in files
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
    if not task:
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

    new_bytes = generate_list(items, changes_summary=changes_summary)

    # Find existing result record (slot='result'), update its bytes; create if missing
    existing_res = await db.execute(
        select(TaskResult)
        .where(TaskResult.task_id == task_id, TaskResult.slot == "result")
        .order_by(TaskResult.created_at.desc())
    )
    existing = existing_res.scalar_one_or_none()

    if existing:
        existing.file_data = new_bytes
        await db.commit()
        await db.refresh(existing)
        return ResultItem(file_id=existing.id, file_name=existing.file_name, mime_type=existing.mime_type)

    # No result record yet — create one with a generic name
    new_record = TaskResult(
        task_id=task_id,
        file_name="Перечень.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_data=new_bytes,
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

    file_stream = io.BytesIO(file_record.file_data)
    filename = file_record.file_name

    # URL-encode filename for Content-Disposition
    import urllib.parse
    encoded_filename = urllib.parse.quote(filename)

    return StreamingResponse(
        file_stream,
        media_type=file_record.mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Content-Length": str(len(file_record.file_data)),
        },
    )

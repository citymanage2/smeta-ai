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

logger = structlog.get_logger()

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

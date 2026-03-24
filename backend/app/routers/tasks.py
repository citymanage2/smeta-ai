import base64
from typing import Optional
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
    status,
    Request,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.database import get_db, AsyncSessionLocal
from app.models.task import Task
from app.utils.auth import get_current_user
from app.config import settings
from app.services.task_processor import process_task

logger = structlog.get_logger()

router = APIRouter(prefix="/tasks", tags=["tasks"])

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/xml",
    "application/xml",
}

# Extension to MIME fallback mapping
EXT_MIME_MAP = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".xml": "text/xml",
}

GSN_REJECTION_MESSAGE = (
    "Формат .gsn не поддерживается. "
    "Экспортируйте смету в XML: Файл → Экспорт → XML"
)


def _get_mime_type(file: UploadFile) -> str:
    """Determine MIME type from content_type or filename extension."""
    if file.content_type and file.content_type != "application/octet-stream":
        return file.content_type.split(";")[0].strip()
    # Fallback to extension
    if file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        return EXT_MIME_MAP.get(ext, file.content_type or "application/octet-stream")
    return file.content_type or "application/octet-stream"


class TaskStatusResponse(BaseModel):
    id: str
    task_type: str
    status: str
    progress_message: Optional[str]
    error_message: Optional[str]
    created_at: str
    updated_at: str


class TaskCreateResponse(BaseModel):
    task_id: str
    status: str


class ChatMessageRequest(BaseModel):
    message: str


async def _run_task_in_background(task_id: str) -> None:
    """Run task processor with its own DB session."""
    async with AsyncSessionLocal() as db:
        try:
            await process_task(task_id, db)
        except Exception as e:
            logger.error("Background task failed", task_id=task_id, error=str(e))


@router.post("", response_model=TaskCreateResponse)
async def create_task(
    request: Request,
    background_tasks: BackgroundTasks,
    task_type: str = Form(...),
    prompt: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create a new processing task with uploaded files."""
    # Validate file count
    if len(files) > settings.MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Превышено максимальное количество файлов ({settings.MAX_FILES_PER_REQUEST})",
        )

    max_size_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    input_file_data = []
    input_files_meta = []

    for file in files:
        # Check for .gsn files
        if file.filename and file.filename.lower().endswith(".gsn"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=GSN_REJECTION_MESSAGE,
            )

        file_data = await file.read()

        # Check file size
        if len(file_data) > max_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Файл '{file.filename}' превышает максимальный размер {settings.MAX_FILE_SIZE_MB} МБ",
            )

        # Validate MIME type
        mime_type = _get_mime_type(file)
        if mime_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"Тип файла '{file.filename}' ({mime_type}) не поддерживается. "
                    "Допустимые форматы: PDF, JPEG, PNG, XLSX, XLS, XML"
                ),
            )

        content_b64 = base64.b64encode(file_data).decode("utf-8")
        input_file_data.append({
            "name": file.filename or "file",
            "mime_type": mime_type,
            "size_bytes": len(file_data),
            "content_b64": content_b64,
        })
        input_files_meta.append({
            "name": file.filename or "file",
            "mime_type": mime_type,
            "size_bytes": len(file_data),
        })

    # Create task record
    task = Task(
        user_role=current_user.get("role", "user"),
        task_type=task_type,
        status="pending",
        input_files=input_files_meta,
        input_file_data=input_file_data,
        user_prompt=prompt,
        chat_history=[],
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    task_id = str(task.id)
    logger.info(
        "Task created",
        task_id=task_id,
        task_type=task_type,
        files=len(files),
    )

    # Launch background processing
    background_tasks.add_task(_run_task_in_background, task_id)

    return TaskCreateResponse(task_id=task_id, status="pending")


@router.get("/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get current status of a task."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задача не найдена",
        )

    return TaskStatusResponse(
        id=str(task.id),
        task_type=task.task_type,
        status=task.status,
        progress_message=task.progress_message,
        error_message=task.error_message,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
    )


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Cancel a pending or processing task."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задача не найдена",
        )

    if task.status not in ("pending", "processing"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Задача не может быть остановлена (статус: {task.status})",
        )

    task.status = "cancelled"
    task.error_message = "Задача остановлена пользователем"
    await db.commit()

    logger.info("Task cancelled by user", task_id=task_id)
    return {"task_id": task_id, "status": "cancelled"}


@router.post("/{task_id}/message")
async def send_message(
    task_id: str,
    body: ChatMessageRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Send a chat message to an existing task and trigger reprocessing."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задача не найдена",
        )

    if task.status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Задача уже обрабатывается. Подождите завершения.",
        )

    # Append message to chat history
    history = list(task.chat_history or [])
    history.append({"role": "user", "content": body.message})
    task.chat_history = history
    task.status = "pending"
    task.error_message = None
    await db.commit()

    # Reprocess
    background_tasks.add_task(_run_task_in_background, task_id)

    return {"task_id": task_id, "status": "pending", "message": "Сообщение принято, задача перезапущена"}

import asyncio
import base64
import io
import time
import uuid
from urllib.parse import quote
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
    status,
    Request,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
import structlog

from app.database import get_db, AsyncSessionLocal
from app.models.task import Task
from app.models.result import TaskResult
from app.models.task_input_file import TaskInputFile
from app.models.history import TaskHistory
from app.models.project import Project
from app.utils.auth import get_current_user, get_download_user
from app.config import settings
from app.services.task_processor import process_task, fix_empty_prices_background
from app.constants import ESTIMATE_TASK_TYPES, TASK_TYPE_TO_FIELD, TASK_TYPE_TO_STAGE, TASK_TYPE_LABELS
from app.models.workflow_card import WorkflowCard
from app.utils.xlsx_cost_parser import extract_total_cost

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

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSX_MIME_ALT = "application/vnd.ms-excel"
VALID_SLOTS = {"source", "result", "estimate", "optimized"}


def _content_disposition(filename: str) -> str:
    """Return Content-Disposition header value with RFC 5987 encoding for non-ASCII filenames."""
    ascii_name = filename.encode("ascii", errors="replace").decode("ascii")
    encoded = quote(filename, safe="")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'


def _get_mime_type(file: UploadFile) -> str:
    """Determine MIME type from content_type or filename extension."""
    if file.content_type and file.content_type != "application/octet-stream":
        return file.content_type.split(";")[0].strip()
    # Fallback to extension
    if file.filename:
        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        return EXT_MIME_MAP.get(ext, file.content_type or "application/octet-stream")
    return file.content_type or "application/octet-stream"


class InputFileMeta(BaseModel):
    name: str
    mime_type: str
    size_bytes: int


class TaskStatusResponse(BaseModel):
    id: str
    task_type: str
    status: str
    progress_message: Optional[str]
    progress_log: list[str] = []
    error_message: Optional[str]
    estimation_status: str
    cost: Optional[float]
    project_id: Optional[str]
    created_at: str
    updated_at: str
    name: Optional[str] = None
    progress_data: Optional[dict] = None
    input_files: list[InputFileMeta] = []


class TaskCreateResponse(BaseModel):
    task_id: str
    status: str


class ChatMessageRequest(BaseModel):
    message: str


class FileSlotResponse(BaseModel):
    task_id: str
    slot: str
    file_name: str
    estimation_status: Optional[str] = None
    cost: Optional[float] = None
    warning: Optional[str] = None


class EstimationConfirmRequest(BaseModel):
    estimation_status: str


class EstimationStatusResponse(BaseModel):
    task_id: str
    estimation_status: str


class ProjectLinkRequest(BaseModel):
    project_id: Optional[str] = None


class ProjectLinkResponse(BaseModel):
    task_id: str
    project_id: Optional[str]


_CONN_ERROR_KEYWORDS = (
    "ConnectionDoesNotExistError",
    "connection was closed",
    "Can't reconnect",
    "SSL SYSCALL",
    "server closed the connection",
    "asyncpg.exceptions",
)


async def _run_task_in_background(task_id: str) -> None:
    """Run task processor with its own DB session, retrying on transient connection errors."""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            async with AsyncSessionLocal() as db:
                await process_task(task_id, db)
            return
        except Exception as e:
            last_exc = e
            err_repr = repr(e)
            is_conn_err = any(kw in err_repr for kw in _CONN_ERROR_KEYWORDS)
            if is_conn_err and attempt < 2:
                delay = 2 ** attempt  # 1s, 2s
                logger.warning(
                    "DB connection lost, retrying task",
                    task_id=task_id,
                    attempt=attempt + 1,
                    delay=delay,
                )
                await asyncio.sleep(delay)
                continue
            break
    logger.error("Background task failed", task_id=task_id, error=str(last_exc))


@router.post("", response_model=TaskCreateResponse)
async def create_task(
    request: Request,
    background_tasks: BackgroundTasks,
    task_type: str = Form(...),
    name: Optional[str] = Form(None),
    prompt: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
    project_name: Optional[str] = Form(None),
    source_task_id: Optional[str] = Form(None),
    source_stage: Optional[int] = Form(None),
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create a new processing task with uploaded files."""
    import json as _json

    # Path B: ESTIMATE_FROM_LIST from existing task — skip file requirement
    is_path_b = task_type == "ESTIMATE_FROM_LIST" and source_task_id

    # Validate file count (skip for Path B)
    if not is_path_b and len(files) > settings.MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Превышено максимальное количество файлов ({settings.MAX_FILES_PER_REQUEST})",
        )

    max_size_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    input_file_data = []
    input_files_meta = []
    raw_file_bytes: list[bytes] = []  # kept in memory only until task_input_files are saved

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

        raw_file_bytes.append(file_data)
        input_file_data.append({
            "name": file.filename or "file",
            "mime_type": mime_type,
            "size_bytes": len(file_data),
        })
        input_files_meta.append({
            "name": file.filename or "file",
            "mime_type": mime_type,
            "size_bytes": len(file_data),
        })

    # Set estimation_status based on task type
    estimation_status = "unestimated" if task_type in ESTIMATE_TASK_TYPES else "not_applicable"

    # For Path B: store source reference in user_prompt as JSON
    resolved_prompt: Optional[str]
    if is_path_b:
        resolved_prompt = _json.dumps({
            "path": "B",
            "source_task_id": source_task_id,
            "source_stage": source_stage or 1,
        }, ensure_ascii=False)
    else:
        resolved_prompt = prompt

    # Create task record
    task = Task(
        id=str(uuid.uuid4()),
        user_role=current_user.get("role", "user"),
        task_type=task_type,
        status="pending",
        input_files=input_files_meta,
        input_file_data=input_file_data,
        user_prompt=resolved_prompt,
        chat_history=[],
        estimation_status=estimation_status,
        name=name.strip() if name and name.strip() else None,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Store each file separately — one INSERT per file so a large PDF
    # never joins a multi-row batch that would overflow the connection buffer.
    for i, (raw_bytes, meta) in enumerate(zip(raw_file_bytes, input_file_data)):
        db.add(TaskInputFile(
            task_id=task.id,
            file_index=i,
            file_name=meta["name"],
            mime_type=meta["mime_type"],
            size_bytes=meta["size_bytes"],
            content=raw_bytes,
        ))
        await db.commit()

    if project_name and not project_id:
        new_proj = Project(name=project_name)
        db.add(new_proj)
        await db.flush()
        task.project_id = str(new_proj.id)
        await db.commit()
        await db.refresh(task)
    elif project_id:
        proj_check = await db.execute(select(Project).where(Project.id == project_id))
        if proj_check.scalar_one_or_none():
            task.project_id = project_id
            await db.commit()

    if task.project_id and task_type in TASK_TYPE_TO_FIELD:
        field_name = TASK_TYPE_TO_FIELD[task_type]
        stage = TASK_TYPE_TO_STAGE[task_type]
        card_name = task.name if task.name else TASK_TYPE_LABELS.get(task_type, task_type)
        card = WorkflowCard(
            id=str(uuid.uuid4()),
            project_id=task.project_id,
            name=card_name,
            stage=stage,
        )
        setattr(card, field_name, task.id)
        db.add(card)
        await db.commit()

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
        progress_log=list(task.progress_log or []),
        error_message=task.error_message,
        estimation_status=task.estimation_status,
        cost=float(task.cost) if task.cost is not None else None,
        project_id=str(task.project_id) if task.project_id else None,
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
        name=task.name,
        progress_data=task.progress_data,
        input_files=[
            InputFileMeta(
                name=f.get("name", ""),
                mime_type=f.get("mime_type", ""),
                size_bytes=f.get("size_bytes", 0),
            )
            for f in (task.input_file_data or task.input_files or [])
        ],
    )


class CheckCompletenessRequest(BaseModel):
    source_task_id: str


@router.post("/check-completeness", response_model=TaskCreateResponse)
async def check_completeness(
    body: CheckCompletenessRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create a CHECK_LIST_COMPLETENESS task for a completed LIST_FROM_GRAND task."""
    result = await db.execute(select(Task).where(Task.id == body.source_task_id))
    source_task = result.scalar_one_or_none()

    if not source_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Исходная задача не найдена",
        )

    if source_task.task_type.upper() != "LIST_FROM_GRAND":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Проверка полноты доступна только для задач «Перечень из Гранд-сметы»",
        )

    if source_task.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Исходная задача должна быть завершена (текущий статус: {source_task.status})",
        )

    task = Task(
        id=str(uuid.uuid4()),
        user_role=current_user.get("role", "user"),
        task_type="CHECK_LIST_COMPLETENESS",
        status="pending",
        input_files=[],
        input_file_data=[],
        user_prompt=body.source_task_id,
        chat_history=[],
        estimation_status="not_applicable",
        project_id=source_task.project_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    task_id = str(task.id)
    background_tasks.add_task(_run_task_in_background, task_id)

    logger.info(
        "CHECK_LIST_COMPLETENESS task created",
        task_id=task_id,
        source_task_id=body.source_task_id,
    )
    return TaskCreateResponse(task_id=task_id, status="pending")


@router.get("/estimate-sources")
async def get_estimate_sources(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return completed LIST_FROM_GRAND / LIST_FROM_PROJECT tasks with available stages for ESTIMATE_FROM_LIST."""
    from sqlalchemy import desc as sa_desc

    result = await db.execute(
        select(Task)
        .where(Task.task_type.in_(["LIST_FROM_GRAND", "LIST_FROM_PROJECT"]))
        .where(Task.status == "completed")
        .order_by(sa_desc(Task.created_at))
        .limit(100)
    )
    source_tasks = result.scalars().all()

    sources = []
    for src in source_tasks:
        items = (src.progress_data or {}).get("items", [])
        if not items:
            continue

        check_type = (
            "CHECK_LIST_COMPLETENESS"
            if src.task_type == "LIST_FROM_GRAND"
            else "CHECK_PROJECT_COMPLETENESS"
        )
        check_result = await db.execute(
            select(Task)
            .where(Task.user_prompt == str(src.id))
            .where(Task.task_type == check_type)
            .where(Task.status == "completed")
            .order_by(sa_desc(Task.created_at))
            .limit(1)
        )
        check_task = check_result.scalar_one_or_none()

        stages = [{"stage": 1, "label": "Исходный перечень", "items_count": len(items)}]
        if check_task:
            check_items = (check_task.progress_data or {}).get("items", [])
            if check_items:
                stages.append({
                    "stage": 2,
                    "label": "После проверки полноты",
                    "items_count": len(check_items),
                    "check_task_id": str(check_task.id),
                })

        sources.append({
            "task_id": str(src.id),
            "task_type": src.task_type,
            "name": src.name,
            "created_at": src.created_at.isoformat(),
            "stages": stages,
        })

    return sources


@router.post("/check-project-completeness", response_model=TaskCreateResponse)
async def check_project_completeness(
    body: CheckCompletenessRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create a CHECK_PROJECT_COMPLETENESS task for a completed LIST_FROM_PROJECT task."""
    result = await db.execute(select(Task).where(Task.id == body.source_task_id))
    source_task = result.scalar_one_or_none()

    if not source_task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Исходная задача не найдена",
        )

    if source_task.task_type.upper() != "LIST_FROM_PROJECT":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Проверка полноты доступна только для задач «Перечень из проекта»",
        )

    if source_task.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Исходная задача должна быть завершена (текущий статус: {source_task.status})",
        )

    task = Task(
        id=str(uuid.uuid4()),
        user_role=current_user.get("role", "user"),
        task_type="CHECK_PROJECT_COMPLETENESS",
        status="pending",
        input_files=[],
        input_file_data=[],
        user_prompt=body.source_task_id,
        chat_history=[],
        estimation_status="not_applicable",
        project_id=source_task.project_id,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    task_id = str(task.id)
    background_tasks.add_task(_run_task_in_background, task_id)

    logger.info(
        "CHECK_PROJECT_COMPLETENESS task created",
        task_id=task_id,
        source_task_id=body.source_task_id,
    )
    return TaskCreateResponse(task_id=task_id, status="pending")


@router.get("/{task_id}/related-checks")
async def get_related_checks(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return the most recent CHECK_LIST_COMPLETENESS and CHECK_PROJECT_COMPLETENESS tasks
    that were created from this source task (identified by user_prompt == task_id)."""
    from sqlalchemy import desc as sa_desc
    check_types = ["CHECK_LIST_COMPLETENESS", "CHECK_PROJECT_COMPLETENESS"]
    result = await db.execute(
        select(Task)
        .where(Task.user_prompt == task_id)
        .where(Task.task_type.in_(check_types))
        .order_by(sa_desc(Task.created_at))
    )
    tasks = result.scalars().all()

    # Keep only the most recent of each type
    seen: set = set()
    related = []
    for t in tasks:
        if t.task_type not in seen:
            seen.add(t.task_type)
            related.append({
                "task_id": str(t.id),
                "task_type": t.task_type,
                "status": t.status,
            })
    return related


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


@router.post("/{task_id}/resume", response_model=TaskCreateResponse)
async def resume_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Resume a failed resumable task from the last saved chunk."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задача не найдена",
        )

    if task.status not in ("failed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Возобновление невозможно: задача в статусе «{task.status}»",
        )

    RESUMABLE_TYPES = {"LIST_FROM_GRAND", "CHECK_LIST_COMPLETENESS", "CHECK_PROJECT_COMPLETENESS"}
    if task.task_type.upper() not in RESUMABLE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Возобновление не поддерживается для данного типа задачи",
        )

    progress_data = task.progress_data or {}
    if "chunks_done" not in progress_data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Нет сохранённого прогресса для возобновления",
        )

    task.status = "pending"
    task.error_message = None
    task.updated_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(_run_task_in_background, task_id)

    logger.info("Task resumed", task_id=task_id, chunks_done=progress_data.get("chunks_done"))
    return TaskCreateResponse(task_id=task_id, status="pending")


@router.post("/{task_id}/restart", response_model=TaskCreateResponse)
async def restart_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Restart a task from scratch, clearing all progress and previous results."""
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
            detail="Нельзя перезапустить задачу, которая сейчас обрабатывается",
        )

    now = datetime.now(timezone.utc)
    task.status = "pending"
    task.error_message = None
    task.progress_message = None
    task.progress_data = None
    task.progress_log = []
    task.created_at = now
    task.updated_at = now
    await db.commit()

    background_tasks.add_task(_run_task_in_background, task_id)

    logger.info("Task restarted from scratch", task_id=task_id)
    return TaskCreateResponse(task_id=task_id, status="pending")


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


@router.post("/{task_id}/files", response_model=FileSlotResponse)
async def upload_file_to_slot(
    task_id: str,
    slot: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недопустимый слот. Допустимые значения: {', '.join(VALID_SLOTS)}",
        )

    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    mime = _get_mime_type(file)
    if mime not in (XLSX_MIME, XLSX_MIME_ALT):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Допустимый формат для файловых слотов: XLSX",
        )

    file_bytes = await file.read()

    existing = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id, TaskResult.slot == slot
        )
    )
    old = existing.scalar_one_or_none()
    if old:
        await db.delete(old)

    new_result = TaskResult(
        task_id=task_id,
        file_name=file.filename or f"{slot}.xlsx",
        mime_type=mime,
        file_data=file_bytes,
        size_bytes=len(file_bytes),
        slot=slot,
    )
    db.add(new_result)

    warning: Optional[str] = None

    if slot == "estimate" and task.task_type in ESTIMATE_TASK_TYPES:
        cost = extract_total_cost(file_bytes)
        if cost is not None:
            task.cost = cost
            task.estimation_status = "estimated"
        else:
            task.cost = None
            task.estimation_status = "unestimated"
            warning = "Строка 'Итого'/'Всего' не найдена или не содержит числового значения. Стоимость не определена."

    await db.commit()
    await db.refresh(task)

    return FileSlotResponse(
        task_id=task_id,
        slot=slot,
        file_name=file.filename or f"{slot}.xlsx",
        estimation_status=task.estimation_status,
        cost=float(task.cost) if task.cost is not None else None,
        warning=warning,
    )


@router.delete("/{task_id}/files/{slot}")
async def delete_file_from_slot(
    task_id: str,
    slot: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недопустимый слот: {slot}",
        )

    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    existing = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id, TaskResult.slot == slot
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        await db.delete(row)

    if slot == "estimate" and task.task_type in ESTIMATE_TASK_TYPES:
        task.cost = None
        task.estimation_status = "unestimated"

    await db.commit()
    return {"task_id": task_id, "slot": slot, "status": "deleted"}


class TaskUpdateRequest(BaseModel):
    name: Optional[str] = None


class TaskUpdateResponse(BaseModel):
    task_id: str
    name: Optional[str]


@router.patch("/{task_id}", response_model=TaskUpdateResponse)
async def update_task(
    task_id: str,
    body: TaskUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    if body.name is not None:
        task.name = body.name.strip() or None
    await db.commit()
    return TaskUpdateResponse(task_id=str(task.id), name=task.name)


class SlotRenameRequest(BaseModel):
    name: str


@router.patch("/{task_id}/files/{slot}")
async def rename_slot_file(
    task_id: str,
    slot: str,
    body: SlotRenameRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недопустимый слот. Допустимые значения: {', '.join(VALID_SLOTS)}",
        )
    result = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id,
            TaskResult.slot == slot,
        )
    )
    task_result = result.scalar_one_or_none()
    if not task_result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    task_result.file_name = body.name.strip()
    await db.commit()
    return {"task_id": task_id, "slot": slot, "file_name": task_result.file_name}


@router.patch("/{task_id}/estimation", response_model=EstimationStatusResponse)
async def confirm_estimation(
    task_id: str,
    body: EstimationConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if body.estimation_status != "optimized":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Допустимое значение: 'optimized'",
        )

    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    slot_result = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id, TaskResult.slot == "optimized"
        )
    )
    if slot_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Файл в слоте 'optimized' отсутствует. Загрузите файл перед подтверждением.",
        )

    task.estimation_status = "optimized"
    await db.commit()
    return EstimationStatusResponse(task_id=task_id, estimation_status="optimized")


@router.patch("/{task_id}/project", response_model=ProjectLinkResponse)
async def link_task_to_project(
    task_id: str,
    body: ProjectLinkRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    if body.project_id is not None:
        proj_result = await db.execute(select(Project).where(Project.id == body.project_id))
        if proj_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Проект не найден",
            )

    task.project_id = body.project_id
    await db.commit()
    return ProjectLinkResponse(task_id=task_id, project_id=body.project_id)


@router.get("/{task_id}/files/{slot}/download")
async def download_file_from_slot(
    task_id: str,
    slot: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_download_user),
):
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Недопустимый слот. Допустимые значения: {', '.join(VALID_SLOTS)}",
        )

    task_row = await db.execute(select(Task).where(Task.id == task_id))
    task = task_row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    # Source slot: serve original uploaded file from task_input_files
    if slot == "source":
        src_row = await db.execute(
            select(TaskInputFile)
            .where(TaskInputFile.task_id == task_id)
            .order_by(TaskInputFile.file_index)
            .limit(1)
        )
        src_file = src_row.scalar_one_or_none()
        if src_file is None and task.input_file_data:
            # backward compat: old task stored content_b64 inline
            first_file = task.input_file_data[0]
            file_bytes = base64.b64decode(first_file.get("content_b64", ""))
            return StreamingResponse(
                io.BytesIO(file_bytes),
                media_type=first_file.get("mime_type", "application/octet-stream"),
                headers={"Content-Disposition": _content_disposition(first_file.get("name", "source"))},
            )
        if src_file is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Исходный файл не найден")
        return StreamingResponse(
            io.BytesIO(src_file.content),
            media_type=src_file.mime_type,
            headers={"Content-Disposition": _content_disposition(src_file.file_name)},
        )

    result_row = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id,
            TaskResult.slot == slot,
        )
    )
    task_result = result_row.scalar_one_or_none()
    if not task_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл в указанном слоте не найден",
        )

    return StreamingResponse(
        io.BytesIO(task_result.file_data),
        media_type=task_result.mime_type or "application/octet-stream",
        headers={"Content-Disposition": _content_disposition(task_result.file_name)},
    )


@router.get("/{task_id}/input-file/{file_index}")
async def download_input_file(
    task_id: str,
    file_index: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_download_user),
):
    """Download one of the original uploaded files by zero-based index."""
    task_row = await db.execute(select(Task).where(Task.id == task_id))
    task = task_row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    # Try new storage first (task_input_files table)
    input_file_row = await db.execute(
        select(TaskInputFile).where(
            TaskInputFile.task_id == task_id,
            TaskInputFile.file_index == file_index,
        )
    )
    input_file = input_file_row.scalar_one_or_none()
    if input_file is not None:
        return StreamingResponse(
            io.BytesIO(input_file.content),
            media_type=input_file.mime_type,
            headers={"Content-Disposition": _content_disposition(input_file.file_name)},
        )

    # Backward compat: old tasks stored content_b64 in input_file_data JSON
    file_data_list = task.input_file_data or []
    if file_index < 0 or file_index >= len(file_data_list):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")

    file_info = file_data_list[file_index]
    raw = base64.b64decode(file_info.get("content_b64", ""))
    return StreamingResponse(
        io.BytesIO(raw),
        media_type=file_info.get("mime_type", "application/octet-stream"),
        headers={"Content-Disposition": _content_disposition(file_info.get("name", "file"))},
    )


# ---------------------------------------------------------------------------
# Input file management endpoints
# ---------------------------------------------------------------------------

@router.delete("/{task_id}/input-file/{file_index}", status_code=204)
async def delete_input_file(
    task_id: str,
    file_index: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Delete one of the original uploaded input files by zero-based index."""
    task_row = await db.execute(select(Task).where(Task.id == task_id))
    task = task_row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    if task.status == "processing":
        raise HTTPException(status_code=400, detail="Нельзя удалить файл во время обработки задачи")

    # Remove from task_input_files table
    await db.execute(
        select(TaskInputFile).where(
            TaskInputFile.task_id == task_id,
            TaskInputFile.file_index == file_index,
        )
    )
    input_file_row = await db.execute(
        select(TaskInputFile).where(
            TaskInputFile.task_id == task_id,
            TaskInputFile.file_index == file_index,
        )
    )
    input_file = input_file_row.scalar_one_or_none()
    if input_file is not None:
        await db.delete(input_file)

    # Update file_index for remaining files
    remaining_rows = await db.execute(
        select(TaskInputFile).where(
            TaskInputFile.task_id == task_id,
            TaskInputFile.file_index > file_index,
        )
    )
    for row in remaining_rows.scalars().all():
        row.file_index -= 1

    # Update task.input_files JSON metadata
    files_meta = list(task.input_files or [])
    if 0 <= file_index < len(files_meta):
        files_meta.pop(file_index)
        task.input_files = files_meta

    await db.commit()


@router.post("/{task_id}/input-files", status_code=200)
async def add_input_file(
    task_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Add a new input file to an existing task."""
    task_row = await db.execute(select(Task).where(Task.id == task_id))
    task = task_row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    if task.status == "processing":
        raise HTTPException(status_code=400, detail="Нельзя добавить файл во время обработки задачи")

    raw_bytes = await file.read()
    mime = (file.content_type or "application/octet-stream").split(";")[0].strip()
    file_name = file.filename or "file"
    size_bytes = len(raw_bytes)

    existing_meta = list(task.input_files or [])
    new_index = len(existing_meta)

    db.add(TaskInputFile(
        task_id=task_id,
        file_index=new_index,
        file_name=file_name,
        mime_type=mime,
        size_bytes=size_bytes,
        content=raw_bytes,
    ))

    existing_meta.append({"name": file_name, "mime_type": mime, "size_bytes": size_bytes})
    task.input_files = existing_meta

    await db.commit()
    return {"name": file_name, "mime_type": mime, "size_bytes": size_bytes, "file_index": new_index}


# ---------------------------------------------------------------------------
# Optimization endpoints
# ---------------------------------------------------------------------------

class OptimizeAnalyzeBody(BaseModel):
    categories: list[str] = ["work", "material"]
    other_description: Optional[str] = None


class OptimizeItem(BaseModel):
    row_index: int
    name: str
    type: str
    quantity: float
    unit: str
    price_excl_vat: float
    price_incl_vat: float
    total: float


class OptimizeRunBody(BaseModel):
    items: list[OptimizeItem]
    prompt: str = ""
    categories: list[str] = ["work", "material"]


@router.post("/{task_id}/optimize/analyze")
async def optimize_analyze(
    task_id: str,
    body: OptimizeAnalyzeBody,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Synchronously parse estimate xlsx and return top-70% items for user review."""
    from app.utils.xlsx_optimizer import parse_estimate_xlsx, get_top_items

    result = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id,
            TaskResult.slot == "estimate",
        )
    )
    task_result = result.scalar_one_or_none()
    if task_result is None:
        raise HTTPException(status_code=404, detail="Файл сметы (слот estimate) не найден")

    try:
        items = parse_estimate_xlsx(task_result.file_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не удалось разобрать xlsx: {e}")

    categories = body.categories or ["work", "material"]
    top_items = get_top_items(items, categories, threshold=0.7)

    total_cost = sum(it["total"] for it in items if it["type"] in categories)
    selected_cost = sum(it["total"] for it in top_items)
    coverage_pct = round(selected_cost / total_cost * 100, 1) if total_cost else 0.0

    return {
        "items": top_items,
        "total_analyzed": len(items),
        "total_selected": len(top_items),
        "coverage_pct": coverage_pct,
    }


OPTIMIZATION_BATCH_SIZE = 4  # позиций обрабатывается параллельно


async def _process_single_item(
    item: dict,
    price_service,
    prompt: str,
) -> dict:
    """Обработать одну позицию сметы: найти цену, вернуть optimization_result.

    Не обращается к БД — только вычисляет.
    Все исключения поглощает внутри и возвращает заглушку.
    """
    name = item["name"]
    item_type = item["type"]
    original_price = item["price_incl_vat"]

    found_price = None
    source = "Не найдено"

    try:
        if item_type == "work":
            price_data = await price_service.find_work_price(name, user_prompt=prompt)
            if price_data:
                found_price = float(price_data["min_price"])
                source = price_data.get("source", "Прайс-лист")
        else:
            material_price = await price_service.find_material_price(name, user_prompt=prompt)
            if material_price is not None:
                found_price = float(material_price)
                source = "Прайс-лист"
    except Exception:
        source = "Ошибка поиска"

    savings_abs = None
    savings_pct = None
    if found_price is not None and found_price < original_price:
        savings_abs = round(original_price - found_price, 4)
        savings_pct = round(savings_abs / original_price * 100, 2)
    elif found_price is not None:
        found_price = None
        source = "Не найдено (цена не ниже)"

    return {
        "row_index": item["row_index"],
        "name": name,
        "original_price": original_price,
        "new_price": found_price,
        "source": source,
        "savings_abs": savings_abs,
        "savings_pct": savings_pct,
        "has_vat": True,
    }


async def _run_optimization_background(
    task_id: str,
    items: list[dict],
    prompt: str,
    estimate_bytes: bytes,
    session_factory,
):
    """Background task: search lower prices for the same items and generate optimized xlsx."""
    import structlog as _structlog
    from app.utils.xlsx_optimizer import generate_optimized_xlsx
    from app.services.price_service import PriceService

    _logger = _structlog.get_logger()

    async with session_factory() as db:
        try:
            task = await db.get(Task, task_id)
            if not task:
                return

            # Check if an "optimized" slot already exists (previous run)
            prev_result_q = await db.execute(
                select(TaskResult).where(
                    TaskResult.task_id == task_id,
                    TaskResult.slot == "optimized",
                )
            )
            prev_optimized = prev_result_q.scalar_one_or_none()
            prev_estimation_status = "optimized" if prev_optimized else "estimated"

            # Count existing versioned snapshots to determine the next archive slot name
            version_rows_q = await db.execute(
                select(TaskResult).where(
                    TaskResult.task_id == task_id,
                    TaskResult.slot.like("optimized_v%"),
                )
            )
            version_count = len(version_rows_q.scalars().all())

            import asyncio as _asyncio
            price_service = PriceService()
            total = len(items)

            # 6.3 — Возобновление после сбоя: читаем уже сохранённые результаты
            already_done: dict[int, dict] = {}
            if task.progress_data:
                for r in task.progress_data.get("partial_results", []):
                    already_done[r["row_index"]] = r

            items_to_process = [i for i in items if i["row_index"] not in already_done]
            optimization_results: list[dict] = list(already_done.values())

            if already_done:
                _logger.info(
                    "optimization_resumed",
                    task_id=task_id,
                    already_done=len(already_done),
                    remaining=len(items_to_process),
                )

            start_time = time.monotonic()
            for batch_start in range(0, len(items_to_process), OPTIMIZATION_BATCH_SIZE):
                batch = items_to_process[batch_start: batch_start + OPTIMIZATION_BATCH_SIZE]

                batch_results = await _asyncio.gather(
                    *[_process_single_item(item, price_service, prompt) for item in batch],
                    return_exceptions=True,
                )

                for idx, r in enumerate(batch_results):
                    if isinstance(r, Exception):
                        failed_item = batch[idx]
                        _logger.warning("batch_item_failed", name=failed_item["name"], error=str(r))
                        optimization_results.append({
                            "row_index": failed_item["row_index"],
                            "name": failed_item["name"],
                            "original_price": failed_item["price_incl_vat"],
                            "new_price": None,
                            "source": "Ошибка поиска",
                            "savings_abs": None,
                            "savings_pct": None,
                            "has_vat": True,
                        })
                    else:
                        optimization_results.append(r)

                # 6.3 — Сохраняем чекпоинт после каждого батча
                task.progress_data = {"partial_results": optimization_results}

                # 7.1 + 7.2 — Детальный прогресс с ETA
                processed_count = len(optimization_results)
                found_count = sum(1 for r in optimization_results if r["new_price"] is not None)
                current_name = batch[0]["name"][:35]
                elapsed = time.monotonic() - start_time
                eta_part = ""
                if processed_count > 0:
                    avg_per_item = elapsed / processed_count
                    remaining_count = total - processed_count
                    eta_sec = int(avg_per_item * remaining_count)
                    if eta_sec > 30:
                        eta_part = f" | осталось ~{eta_sec // 60} мин"
                task.progress_message = (
                    f"Ищем цены: {processed_count}/{total} позиций"
                    f" | найдено {found_count}"
                    f" | текущая: {current_name}..."
                    f"{eta_part}"
                )
                await db.commit()

            optimized_bytes = generate_optimized_xlsx(estimate_bytes, optimization_results)
            found_count = sum(1 for r in optimization_results if r["new_price"] is not None)

            # Archive the previous "optimized" slot by renaming it to a versioned snapshot.
            # This avoids storing file bytes in the JSON history field.
            if prev_optimized:
                archive_slot = f"optimized_v{version_count + 1}"
                prev_optimized.slot = archive_slot
                previous_value: dict = {
                    "result_slot": archive_slot,
                    "file_name": prev_optimized.file_name,
                    "estimation_status": "optimized",
                }
                # Create fresh "optimized" slot with new bytes
                db.add(TaskResult(
                    task_id=task_id,
                    slot="optimized",
                    file_name="optimized.xlsx",
                    mime_type=XLSX_MIME,
                    file_data=optimized_bytes,
                    size_bytes=len(optimized_bytes),
                ))
            else:
                previous_value = {"estimation_status": prev_estimation_status}
                db.add(TaskResult(
                    task_id=task_id,
                    slot="optimized",
                    file_name="optimized.xlsx",
                    mime_type=XLSX_MIME,
                    file_data=optimized_bytes,
                    size_bytes=len(optimized_bytes),
                ))

            # History entry contains only metadata — no file bytes
            history = TaskHistory(
                id=str(uuid.uuid4()),
                task_id=task_id,
                operation_type="optimization",
                slot="optimized",
                description=f"Поиск сниженных цен: найдено {found_count} из {total} позиций",
                previous_value=previous_value,
                new_value={"estimation_status": "optimized"},
            )
            db.add(history)

            task.status = "completed"
            task.estimation_status = "optimized"
            task.progress_message = None
            task.progress_data = None  # 6.4 — чекпоинт больше не нужен
            await db.commit()
            _logger.info("optimization_complete", task_id=task_id)

        except Exception as e:
            _logger.error("optimization_failed", task_id=task_id, error=str(e))
            try:
                task = await db.get(Task, task_id)
                if task:
                    task.status = "failed"
                    task.error_message = str(e)
                    await db.commit()
            except Exception:
                pass


@router.post("/{task_id}/optimize/run")
async def optimize_run(
    task_id: str,
    body: OptimizeRunBody,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Start background optimization: search lower prices for the same items and generate optimized xlsx."""
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    result = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id,
            TaskResult.slot == "estimate",
        )
    )
    task_result = result.scalar_one_or_none()
    if task_result is None:
        raise HTTPException(status_code=404, detail="Файл сметы (слот estimate) не найден")

    estimate_bytes = task_result.file_data

    task.status = "processing"
    task.estimation_status = "optimizing"
    task.progress_message = "Начинаем оптимизацию..."
    await db.commit()

    items_dicts = [item.model_dump() for item in body.items]

    background_tasks.add_task(
        _run_optimization_background,
        task_id,
        items_dicts,
        body.prompt,
        estimate_bytes,
        AsyncSessionLocal,
    )

    return {"task_id": task_id, "status": "optimization_started"}


# ---------------------------------------------------------------------------
# ESTIMATE_FROM_LIST — редактирование позиций и переопределение цен
# ---------------------------------------------------------------------------

class EstimateItemsUpdateRequest(BaseModel):
    items: list[dict]


@router.post("/{task_id}/estimate-items/fix-empty-prices")
async def fix_empty_prices(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Запустить фоновое исправление позиций с пустыми ценами.

    Находит в progress_data.items позиции с null/0 ценой, отправляет в Claude
    батчами по 5, сохраняет результат и пересоздаёт xlsx.
    Возвращает 202 немедленно; задача переходит в status=processing на время работы.
    """
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.task_type != "ESTIMATE_FROM_LIST":
        raise HTTPException(status_code=409, detail="Доступно только для задач типа ESTIMATE_FROM_LIST")
    if task.status == "processing":
        raise HTTPException(status_code=409, detail="Задача уже выполняется")

    items: list[dict] = (task.progress_data or {}).get("items", [])

    def _has_empty(it: dict) -> bool:
        if it.get("type") == "Работа":
            return not it.get("work_price")
        if it.get("type") == "Материал":
            return not it.get("material_price")
        return False

    empty_count = sum(1 for it in items if _has_empty(it))

    if empty_count == 0:
        return {"empty_count": 0, "status": "no_empty_items"}

    task.status = "processing"
    task.progress_message = f"Исправление {empty_count} пустых цен..."
    task.updated_at = datetime.now(timezone.utc)
    await db.commit()

    background_tasks.add_task(fix_empty_prices_background, task_id, AsyncSessionLocal)

    return {"empty_count": empty_count, "status": "started"}


@router.patch("/{task_id}/estimate-items")
async def update_estimate_items(
    task_id: str,
    body: EstimateItemsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Пересохранить позиции сметы: пересоздать Excel и обновить cost."""
    from app.utils.xlsx_exporter import generate_estimate_xlsx
    from decimal import Decimal as _Decimal

    task_row = await db.execute(select(Task).where(Task.id == task_id))
    task = task_row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.task_type != "ESTIMATE_FROM_LIST":
        raise HTTPException(status_code=409, detail="Доступно только для задач типа ESTIMATE_FROM_LIST")

    excel_data, grand_total = generate_estimate_xlsx(body.items)

    # Update or create the "estimate" slot result
    existing_r = await db.execute(
        select(TaskResult).where(TaskResult.task_id == task_id, TaskResult.slot == "estimate")
    )
    old_result = existing_r.scalar_one_or_none()
    if old_result:
        old_result.file_data = excel_data
        old_result.size_bytes = len(excel_data)
        old_result.file_name = "Смета_из_перечня.xlsx"
    else:
        db.add(TaskResult(
            task_id=task_id,
            file_name="Смета_из_перечня.xlsx",
            mime_type=XLSX_MIME,
            file_data=excel_data,
            size_bytes=len(excel_data),
            slot="estimate",
        ))

    task.cost = _Decimal(str(round(grand_total, 2)))
    task.estimation_status = "estimated"
    task.progress_data = {**(task.progress_data or {}), "items": body.items}
    task.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"task_id": task_id, "grand_total": round(grand_total, 2), "items_count": len(body.items)}


@router.post("/{task_id}/estimate-items/{item_index}/reprice")
async def reprice_estimate_item(
    task_id: str,
    item_index: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Переопределить цену одной позиции сметы через Claude (промпт 2)."""
    from datetime import date as _date
    from app.services.claude_service import call_claude
    from app.utils.json_utils import extract_json

    task_row = await db.execute(select(Task).where(Task.id == task_id))
    task = task_row.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.task_type != "ESTIMATE_FROM_LIST":
        raise HTTPException(status_code=409, detail="Доступно только для задач типа ESTIMATE_FROM_LIST")

    items = (task.progress_data or {}).get("items", [])
    if item_index < 0 or item_index >= len(items):
        raise HTTPException(status_code=404, detail="Позиция не найдена")

    item = items[item_index]
    current_date = _date.today().strftime("%d.%m.%Y")

    prompt_text = (
        "Ты — эксперт по строительному сметному делу в России.\n\n"
        "Найди актуальную рыночную цену для одной позиции.\n\n"
        f"Текущая дата: {current_date}\n"
        "Регион: г. Екатеринбург, Свердловская область\n\n"
        "Позиция:\n"
        f"- Тип: {item.get('type', '')}\n"
        f"- Наименование: {item.get('name', '')}\n"
        f"- Единица измерения: {item.get('unit', '')}\n\n"
        "Инструкция:\n"
        "1. Найди 3 актуальных цены в г. Екатеринбург\n"
        "2. Поставь среднюю из трёх\n"
        "3. Перечисли все 3 источника с ценами\n\n"
        "Верни СТРОГО в формате JSON, без markdown:\n"
        '{"work_price": число или null, "material_price": число или null, '
        '"sources": "Источник 1: цена; Источник 2: цена; Источник 3: цена", '
        '"notes": "Примечание по НДС"}'
    )

    try:
        response_text = await call_claude(
            messages=[{"role": "user", "content": prompt_text}],
            use_web_search=True,
            processing_timeout=120.0,
        )
        data = extract_json(response_text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка при обращении к Claude: {e}")

    new_price = data.get("work_price") if item.get("type") == "Работа" else data.get("material_price")
    if new_price is not None:
        from sqlalchemy.orm.attributes import flag_modified
        from app.utils.xlsx_exporter import generate_estimate_xlsx
        from decimal import Decimal as _Decimal
        updated_item = {
            **item,
            "work_price": data.get("work_price"),
            "material_price": data.get("material_price"),
            "sources": data.get("sources", ""),
            "notes": data.get("notes", ""),
            "price_list_name": None,
        }
        items[item_index] = updated_item
        task.progress_data = {**(task.progress_data or {}), "items": items}
        flag_modified(task, "progress_data")
        excel_data, grand_total = generate_estimate_xlsx(items)
        existing_r = await db.execute(
            select(TaskResult).where(TaskResult.task_id == task_id, TaskResult.slot == "estimate")
        )
        old_result = existing_r.scalar_one_or_none()
        if old_result:
            old_result.file_data = excel_data
            old_result.size_bytes = len(excel_data)
            old_result.file_name = "Смета_из_перечня.xlsx"
        else:
            db.add(TaskResult(
                task_id=task_id,
                file_name="Смета_из_перечня.xlsx",
                mime_type=XLSX_MIME,
                file_data=excel_data,
                size_bytes=len(excel_data),
                slot="estimate",
            ))
        task.cost = _Decimal(str(round(grand_total, 2)))
        task.estimation_status = "estimated"
        task.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return {
        "item_index": item_index,
        "work_price": data.get("work_price"),
        "material_price": data.get("material_price"),
        "sources": data.get("sources", ""),
        "notes": data.get("notes", ""),
    }


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class HistoryEntryOut(BaseModel):
    id: str
    operation_type: str
    slot: str
    description: str
    created_at: str


@router.get("/{task_id}/history")
async def get_task_history(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return list of history entries for a task (without file_data_b64)."""
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    result = await db.execute(
        select(TaskHistory)
        .where(TaskHistory.task_id == task_id)
        .order_by(TaskHistory.created_at.desc())
    )
    entries = result.scalars().all()
    return [
        HistoryEntryOut(
            id=e.id,
            operation_type=e.operation_type,
            slot=e.slot,
            description=e.description,
            created_at=e.created_at.isoformat(),
        )
        for e in entries
    ]


class RevertBody(BaseModel):
    confirm: bool = False


@router.post("/{task_id}/history/{entry_id}/revert")
async def revert_history(
    task_id: str,
    entry_id: str,
    body: RevertBody,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Revert task to state before a given history entry.

    confirm=False: if there are later dependent entries, returns a warning list.
                   If no dependents, executes rollback immediately.
    confirm=True:  executes cascade rollback unconditionally.
    """
    import base64 as _b64

    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    entry_result = await db.execute(
        select(TaskHistory).where(
            TaskHistory.task_id == task_id,
            TaskHistory.id == entry_id,
        )
    )
    entry = entry_result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Запись истории не найдена")

    # Find dependent entries (created after this entry)
    dep_result = await db.execute(
        select(TaskHistory)
        .where(
            TaskHistory.task_id == task_id,
            TaskHistory.created_at > entry.created_at,
        )
        .order_by(TaskHistory.created_at.asc())
    )
    dependent = dep_result.scalars().all()

    if not body.confirm and dependent:
        return {
            "warning": True,
            "dependent_entries": [
                {
                    "id": d.id,
                    "description": d.description,
                    "created_at": d.created_at.isoformat(),
                }
                for d in dependent
            ],
        }

    # Execute rollback
    prev = entry.previous_value or {}

    # Delete current TaskResult for this slot
    cur_result = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == task_id,
            TaskResult.slot == entry.slot,
        )
    )
    current_file = cur_result.scalar_one_or_none()
    if current_file:
        await db.delete(current_file)
        await db.flush()

    if prev.get("result_slot"):
        # New format: restore by renaming the versioned snapshot back to the active slot
        versioned_q = await db.execute(
            select(TaskResult).where(
                TaskResult.task_id == task_id,
                TaskResult.slot == prev["result_slot"],
            )
        )
        versioned = versioned_q.scalar_one_or_none()
        if versioned:
            versioned.slot = entry.slot
    elif prev.get("file_data_b64"):
        # Backward compat: old entries stored file bytes as base64 in JSON
        restored_bytes = _b64.b64decode(prev["file_data_b64"])
        db.add(TaskResult(
            task_id=task_id,
            slot=entry.slot,
            file_name=prev.get("file_name", "restored.xlsx"),
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_data=restored_bytes,
            size_bytes=len(restored_bytes),
        ))
    # else: no file to restore (e.g., reverting the very first optimization → back to "estimated")

    # Restore task estimation_status
    task.estimation_status = prev.get("estimation_status", "estimated")

    # Delete this entry and all later entries for this task
    await db.execute(
        delete(TaskHistory).where(
            TaskHistory.task_id == task_id,
            TaskHistory.created_at >= entry.created_at,
        )
    )

    # Write revert entry
    revert_entry = TaskHistory(
        id=str(uuid.uuid4()),
        task_id=task_id,
        operation_type="revert",
        slot=entry.slot,
        description=f"Откат к состоянию до: {entry.description}",
        previous_value=entry.new_value,
        new_value=prev,
    )
    db.add(revert_entry)
    await db.commit()

    return {"reverted": True}


# ---------------------------------------------------------------------------
# User trash endpoints
# ---------------------------------------------------------------------------

class TrashTaskItem(BaseModel):
    id: str
    task_type: str
    status: str
    name: Optional[str]
    created_at: str
    deleted_at: str


class TrashTasksResponse(BaseModel):
    items: list[TrashTaskItem]
    total: int


@router.get("/trash", response_model=TrashTasksResponse)
async def list_my_trash(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Список удалённых задач текущего пользователя."""
    role = current_user.get("role", "user")
    conditions = [Task.deleted_at.is_not(None), Task.user_role == role]

    count_result = await db.execute(select(func.count(Task.id)).where(*conditions))
    total = count_result.scalar() or 0

    data_query = (
        select(Task.id, Task.task_type, Task.status, Task.name, Task.created_at, Task.deleted_at)
        .where(*conditions)
        .order_by(Task.deleted_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(data_query)
    rows = result.all()

    items = [
        TrashTaskItem(
            id=str(row.id),
            task_type=row.task_type,
            status=row.status,
            name=row.name,
            created_at=row.created_at.isoformat(),
            deleted_at=row.deleted_at.isoformat(),
        )
        for row in rows
    ]
    return TrashTasksResponse(items=items, total=total)


@router.delete("/trash", status_code=status.HTTP_204_NO_CONTENT)
async def clear_my_trash(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Удалить все задачи из корзины текущего пользователя навсегда."""
    role = current_user.get("role", "user")
    await db.execute(
        delete(Task).where(Task.deleted_at.is_not(None), Task.user_role == role)
    )
    await db.commit()
    logger.info("Trash cleared", role=role)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def soft_delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Мягкое удаление задачи — перемещает в корзину."""
    result = await db.execute(select(Task).where(Task.id == task_id, Task.deleted_at.is_(None)))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    task.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("Task soft-deleted", task_id=task_id, role=current_user.get("role"))


@router.post("/{task_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore_my_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Восстановить задачу из корзины."""
    result = await db.execute(select(Task).where(Task.id == task_id, Task.deleted_at.is_not(None)))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена или не удалена")
    task.deleted_at = None
    await db.commit()
    logger.info("Task restored from trash", task_id=task_id, role=current_user.get("role"))


@router.delete("/{task_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def permanent_delete_my_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Окончательное удаление задачи."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await db.delete(task)
    await db.commit()
    logger.info("Task permanently deleted", task_id=task_id, role=current_user.get("role"))

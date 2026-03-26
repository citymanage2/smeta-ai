import base64
import io
import uuid
from decimal import Decimal
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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.database import get_db, AsyncSessionLocal
from app.models.task import Task
from app.models.result import TaskResult
from app.models.project import Project
from app.utils.auth import get_current_user
from app.config import settings
from app.services.task_processor import process_task
from app.constants import ESTIMATE_TASK_TYPES
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
VALID_SLOTS = {"source", "estimate", "optimized"}


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
    estimation_status: str
    cost: Optional[float]
    project_id: Optional[str]
    created_at: str
    updated_at: str


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
    project_id: Optional[str] = Form(None),
    project_name: Optional[str] = Form(None),
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

    # Set estimation_status based on task type
    estimation_status = "unestimated" if task_type in ESTIMATE_TASK_TYPES else "not_applicable"

    # Create task record
    task = Task(
        id=str(uuid.uuid4()),
        user_role=current_user.get("role", "user"),
        task_type=task_type,
        status="pending",
        input_files=input_files_meta,
        input_file_data=input_file_data,
        user_prompt=prompt,
        chat_history=[],
        estimation_status=estimation_status,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

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
        estimation_status=task.estimation_status,
        cost=float(task.cost) if task.cost is not None else None,
        project_id=str(task.project_id) if task.project_id else None,
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
    current_user: dict = Depends(get_current_user),
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
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{task_result.file_name}"',
        },
    )


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


async def _run_optimization_background(
    task_id: str,
    items: list[dict],
    prompt: str,
    estimate_bytes: bytes,
    session_factory,
):
    """Background task: search analogues and generate optimized xlsx."""
    import structlog as _structlog
    from app.utils.xlsx_optimizer import generate_optimized_xlsx
    from app.services.price_service import PriceService

    _logger = _structlog.get_logger()

    async with session_factory() as db:
        try:
            task = await db.get(Task, task_id)
            if not task:
                return

            price_service = PriceService(db)
            optimization_results = []
            total = len(items)

            for i, item in enumerate(items):
                name = item["name"]
                item_type = item["type"]
                original_price = item["price_incl_vat"]

                task.progress_message = f"Обработано {i}/{total}: {name[:40]}"
                await db.commit()

                found_price = None
                source = "Не найдено"

                try:
                    if item_type == "work":
                        price_data = await price_service.find_work_price(name)
                    else:
                        price_data = await price_service.find_material_price(name)

                    if price_data and price_data.get("price"):
                        found_price = float(price_data["price"])
                        source = price_data.get("source", "Прайс-лист")
                except Exception as e:
                    _logger.warning("price_search_failed", name=name, error=str(e))

                savings_abs = None
                savings_pct = None
                if found_price is not None and found_price < original_price:
                    savings_abs = round(original_price - found_price, 4)
                    savings_pct = round(savings_abs / original_price * 100, 2)
                elif found_price is not None:
                    found_price = None
                    source = "Не найдено (цена не ниже)"

                optimization_results.append({
                    "row_index": item["row_index"],
                    "name": name,
                    "original_price": original_price,
                    "new_price": found_price,
                    "source": source,
                    "savings_abs": savings_abs,
                    "savings_pct": savings_pct,
                    "has_vat": True,
                })

            optimized_bytes = generate_optimized_xlsx(estimate_bytes, optimization_results)

            existing = await db.execute(
                select(TaskResult).where(
                    TaskResult.task_id == task_id,
                    TaskResult.slot == "optimized",
                )
            )
            existing_result = existing.scalar_one_or_none()
            if existing_result:
                existing_result.file_data = optimized_bytes
                existing_result.file_name = "optimized.xlsx"
            else:
                new_result = TaskResult(
                    task_id=task_id,
                    slot="optimized",
                    file_name="optimized.xlsx",
                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    file_data=optimized_bytes,
                )
                db.add(new_result)

            task.status = "completed"
            task.estimation_status = "optimized"
            task.progress_message = None
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
    """Start background optimization: search analogues and generate optimized xlsx."""
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
    task.estimation_status = "processing_optimization"
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

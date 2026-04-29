import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    UploadFile,
    File,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.project import Project
from app.models.result import TaskResult
from app.models.task import Task
from app.models.task_input_file import TaskInputFile
from app.models.workflow_card import WorkflowCard
from app.schemas.workflow_card import (
    WorkflowCardCreate,
    WorkflowCardResponse,
    WorkflowCardUpdate,
    TaskBrief,
    InputFileBrief,
)
from app.utils.auth import get_current_user
from app.constants import ESTIMATE_TASK_TYPES

logger = structlog.get_logger()

router = APIRouter(tags=["workflow-cards"])

_COMPLETENESS_TYPES = {"CHECK_LIST_COMPLETENESS", "CHECK_PROJECT_COMPLETENESS"}
_LIST_TYPES = {"LIST_FROM_GRAND", "LIST_FROM_PROJECT"}

_TASK_TYPE_TO_FIELD = {
    "LIST_FROM_GRAND": "list_task_id",
    "LIST_FROM_PROJECT": "list_task_id",
    "CHECK_LIST_COMPLETENESS": "completeness_task_id",
    "CHECK_PROJECT_COMPLETENESS": "completeness_task_id",
    "ESTIMATE_FROM_LIST": "estimate_task_id",
    "ESTIMATE_OPTIMIZATION": "optimization_task_id",
}


def _build_card_response(card: WorkflowCard) -> WorkflowCardResponse:
    def _task_brief(task: Optional[Task]) -> Optional[TaskBrief]:
        if task is None:
            return None
        raw_files = task.input_files or []
        files = [
            InputFileBrief(
                name=f.get("name", ""),
                mime_type=f.get("mime_type", ""),
                size_bytes=f.get("size_bytes", 0),
            )
            for f in raw_files
            if isinstance(f, dict)
        ]
        return TaskBrief(
            id=str(task.id),
            task_type=task.task_type,
            status=task.status,
            name=task.name,
            created_at=task.created_at.isoformat(),
            input_files=files,
            progress_message=task.progress_message,
        )

    return WorkflowCardResponse(
        id=str(card.id),
        project_id=str(card.project_id),
        name=card.name,
        stage=card.stage,
        list_task_id=str(card.list_task_id) if card.list_task_id else None,
        completeness_task_id=str(card.completeness_task_id) if card.completeness_task_id else None,
        estimate_task_id=str(card.estimate_task_id) if card.estimate_task_id else None,
        optimization_task_id=str(card.optimization_task_id) if card.optimization_task_id else None,
        list_task=_task_brief(card.list_task),
        completeness_task=_task_brief(card.completeness_task),
        estimate_task=_task_brief(card.estimate_task),
        optimization_task=_task_brief(card.optimization_task),
        created_at=card.created_at.isoformat(),
        updated_at=card.updated_at.isoformat(),
    )


async def _load_card_with_tasks(card_id: str, db: AsyncSession) -> Optional[WorkflowCard]:
    stmt = (
        select(WorkflowCard)
        .where(WorkflowCard.id == card_id)
        .options(
            selectinload(WorkflowCard.list_task),
            selectinload(WorkflowCard.completeness_task),
            selectinload(WorkflowCard.estimate_task),
            selectinload(WorkflowCard.optimization_task),
        )
    )
    result = await db.execute(stmt)
    card = result.scalar_one_or_none()
    if card is None:
        return None
    _apply_soft_delete_filter(card)
    return card


def _apply_soft_delete_filter(card: WorkflowCard) -> None:
    """Обнуляет task-поля для soft-deleted задач (selectinload не поддерживает WHERE)."""
    for attr in ("list_task", "completeness_task", "estimate_task", "optimization_task"):
        task = object.__getattribute__(card, attr)
        if task is not None and task.deleted_at is not None:
            object.__setattr__(card, attr, None)


@router.get("/projects/{project_id}/workflow-cards", response_model=list[WorkflowCardResponse])
async def get_workflow_cards(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    proj = await db.get(Project, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    stmt = (
        select(WorkflowCard)
        .where(WorkflowCard.project_id == project_id)
        .options(
            selectinload(WorkflowCard.list_task),
            selectinload(WorkflowCard.completeness_task),
            selectinload(WorkflowCard.estimate_task),
            selectinload(WorkflowCard.optimization_task),
        )
        .order_by(WorkflowCard.created_at.asc())
        .limit(100)
    )
    result = await db.execute(stmt)
    cards = result.scalars().all()
    for card in cards:
        _apply_soft_delete_filter(card)
    return [_build_card_response(c) for c in cards]


@router.post("/projects/{project_id}/workflow-cards", response_model=WorkflowCardResponse, status_code=201)
async def create_workflow_card(
    project_id: str,
    body: WorkflowCardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    proj = await db.get(Project, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    card = WorkflowCard(
        id=str(uuid.uuid4()),
        project_id=project_id,
        name=body.name,
        stage="list",
    )
    db.add(card)
    await db.commit()
    await db.refresh(card)

    # После refresh relationship-атрибуты вернут lazy="raise" — обнуляем вручную
    object.__setattr__(card, "list_task", None)
    object.__setattr__(card, "completeness_task", None)
    object.__setattr__(card, "estimate_task", None)
    object.__setattr__(card, "optimization_task", None)

    logger.info("WorkflowCard created", card_id=card.id, project_id=project_id)
    return _build_card_response(card)


@router.patch("/workflow-cards/{card_id}", response_model=WorkflowCardResponse)
async def update_workflow_card(
    card_id: str,
    body: WorkflowCardUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    card = await _load_card_with_tasks(card_id, db)
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")

    if body.name is not None:
        card.name = body.name
    if body.stage is not None:
        card.stage = body.stage

    card.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(card)

    # Перезагружаем с task-relationship после commit
    card = await _load_card_with_tasks(card_id, db)
    return _build_card_response(card)


@router.delete("/workflow-cards/{card_id}", status_code=204)
async def delete_workflow_card(
    card_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(WorkflowCard).where(WorkflowCard.id == card_id))
    card = result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")

    task_ids = [tid for tid in [
        card.list_task_id,
        card.completeness_task_id,
        card.estimate_task_id,
        card.optimization_task_id,
    ] if tid is not None]

    # Удаляем задачи первыми — FK на карточке обнуляется SET NULL,
    # CASCADE чистит TaskResult / TaskInputFile / TaskHistory
    for task_id in task_ids:
        task = await db.get(Task, task_id)
        if task is not None:
            await db.delete(task)

    await db.flush()
    await db.delete(card)
    await db.commit()
    logger.info("WorkflowCard deleted with tasks", card_id=card_id, task_count=len(task_ids))


@router.post("/workflow-cards/{card_id}/start-task", response_model=WorkflowCardResponse)
async def start_task(
    card_id: str,
    background_tasks: BackgroundTasks,
    task_type: str = Form(...),
    source_stage: Optional[int] = Form(None),
    use_previous_stage: Optional[bool] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Атомарно создаёт задачу и привязывает её к карточке в одной транзакции."""
    from app.routers.tasks import _run_task_in_background

    card = await _load_card_with_tasks(card_id, db)
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")

    field_name = _TASK_TYPE_TO_FIELD.get(task_type)
    if field_name is None:
        raise HTTPException(status_code=400, detail=f"Неизвестный task_type: {task_type}")

    estimation_status = "unestimated" if task_type in ESTIMATE_TASK_TYPES else "not_applicable"
    user_role = current_user.get("role", "user")

    # --- Подготовка файлов и user_prompt ---
    input_files_meta: list[dict] = []
    raw_file_bytes: Optional[bytes] = None
    resolved_prompt: Optional[str] = None

    if task_type == "ESTIMATE_FROM_LIST":
        # Path B: берём файл из существующей задачи
        src_stage = source_stage or 1
        src_task_id = (
            card.completeness_task_id if src_stage == 2 else card.list_task_id
        )
        if not src_task_id:
            raise HTTPException(
                status_code=400,
                detail="Источник для сметы недоступен (задача не создана)",
            )
        resolved_prompt = json.dumps(
            {"path": "B", "source_task_id": src_task_id, "source_stage": src_stage},
            ensure_ascii=False,
        )

    elif task_type == "ESTIMATE_OPTIMIZATION" and use_previous_stage:
        # Берём файл из TaskResult estimate_task
        if not card.estimate_task_id:
            raise HTTPException(
                status_code=400,
                detail="Файл сметы недоступен: сначала создайте смету на стадии «Смета»",
            )
        result_row = await db.execute(
            select(TaskResult)
            .where(TaskResult.task_id == card.estimate_task_id)
            .where(TaskResult.slot == "estimate")
        )
        tr = result_row.scalar_one_or_none()
        if tr is None:
            raise HTTPException(
                status_code=400,
                detail="Файл сметы недоступен: результат не найден",
            )
        raw_file_bytes = tr.file_data
        input_files_meta = [
            {"name": tr.file_name, "mime_type": tr.mime_type, "size_bytes": len(tr.file_data)}
        ]

    elif task_type in _COMPLETENESS_TYPES:
        # Источник — list_task
        if not card.list_task_id:
            raise HTTPException(
                status_code=400,
                detail="Для проверки полноты необходим завершённый Перечень",
            )
        resolved_prompt = card.list_task_id

    elif file is not None:
        # Обычная загрузка файла (LIST_FROM_GRAND, LIST_FROM_PROJECT, ESTIMATE_OPTIMIZATION)
        raw_file_bytes = await file.read()
        mime = (file.content_type or "application/octet-stream").split(";")[0].strip()
        input_files_meta = [
            {"name": file.filename or "file", "mime_type": mime, "size_bytes": len(raw_file_bytes)}
        ]

    # --- Атомарная транзакция: создать Task + обновить карточку ---
    task_id = str(uuid.uuid4())
    new_task = Task(
        id=task_id,
        user_role=user_role,
        task_type=task_type,
        status="pending",
        input_files=input_files_meta,
        input_file_data=input_files_meta,
        user_prompt=resolved_prompt,
        chat_history=[],
        estimation_status=estimation_status,
        project_id=card.project_id,
    )
    db.add(new_task)
    await db.flush()  # получаем task.id, не коммитим

    # Сохраняем файл в task_input_files если он есть
    if raw_file_bytes is not None and input_files_meta:
        meta = input_files_meta[0]
        db.add(TaskInputFile(
            task_id=task_id,
            file_index=0,
            file_name=meta["name"],
            mime_type=meta["mime_type"],
            size_bytes=meta["size_bytes"],
            content=raw_file_bytes,
        ))

    # Привязываем задачу к карточке
    setattr(card, field_name, task_id)
    card.updated_at = datetime.now(timezone.utc)

    await db.commit()  # единый commit — при ошибке rollback оба изменения

    logger.info("start-task atomic commit", card_id=card_id, task_id=task_id, task_type=task_type)

    # Запускаем фоновую обработку после commit
    background_tasks.add_task(_run_task_in_background, task_id)

    # Возвращаем обновлённую карточку
    updated_card = await _load_card_with_tasks(card_id, db)
    return _build_card_response(updated_card)

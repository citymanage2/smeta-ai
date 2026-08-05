import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

import structlog
from pydantic import BaseModel
import hashlib

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    UploadFile,
    File,
    Request,
    Response,
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
from app.services import eta_service, storage_service, usage_metrics
from app.schemas.workflow_card import (
    WorkflowCardCreate,
    WorkflowCardResponse,
    WorkflowCardUpdate,
    TaskBrief,
    TaskUsage,
    InputFileBrief,
    CardDetailResponse,
    StageDetail,
    InputFileDetail,
    ResultFileDetail,
)
from app.utils.auth import get_current_user, current_user_id
from app.utils.permissions import can_access
from app.utils.progress_summary import build_progress_summary
from app.constants import ESTIMATE_TASK_TYPES, TASK_TYPE_TO_FIELD

logger = structlog.get_logger()

router = APIRouter(tags=["workflow-cards"])

_COMPLETENESS_TYPES = {"CHECK_LIST_COMPLETENESS", "CHECK_PROJECT_COMPLETENESS"}
_LIST_TYPES = {"LIST_FROM_GRAND", "LIST_FROM_PROJECT"}

_TASK_TYPE_TO_FIELD = TASK_TYPE_TO_FIELD


_STAGE_ATTRS = ("list_task", "completeness_task", "estimate_task", "optimization_task")


def _card_tasks(cards: list[WorkflowCard]) -> list[Task]:
    """Все задачи всех карточек одним списком — вход агрегатора метрик."""
    return [
        task
        for card in cards
        for attr in _STAGE_ATTRS
        if (task := getattr(card, attr)) is not None
    ]


async def _cards_usage(db: AsyncSession, cards: list[WorkflowCard]) -> dict:
    """Метрики затрат по всем задачам всех карточек — ОДНИМ запросом.

    Список карточек поллится каждые 5 секунд: запрос на карточку превратился бы
    здесь в сотни запросов в минуту.
    """
    return await usage_metrics.usage_for_tasks(db, _card_tasks(cards))


def _build_card_response(
    card: WorkflowCard,
    forecast: Optional[dict] = None,
    usage: Optional[dict] = None,
) -> WorkflowCardResponse:
    forecast = forecast or {}
    usage = usage or {}

    def _task_brief(task: Optional[Task]) -> Optional[TaskBrief]:
        if task is None:
            return None
        metrics = usage.get(str(task.id))
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
            progress_data=build_progress_summary(task.progress_data),
            eta=forecast.get(str(task.id)),
            cost=float(task.cost) if task.cost is not None else None,
            usage=TaskUsage(**asdict(metrics)) if metrics is not None else None,
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
        primary_version_id=str(card.primary_version_id) if card.primary_version_id else None,
        list_task=_task_brief(card.list_task),
        completeness_task=_task_brief(card.completeness_task),
        estimate_task=_task_brief(card.estimate_task),
        optimization_task=_task_brief(card.optimization_task),
        created_at=card.created_at.isoformat(),
        updated_at=card.updated_at.isoformat(),
    )


async def _card_forecast(db: AsyncSession, cards: list[WorkflowCard]) -> dict:
    """Прогноз времени по задачам карточек — только если активные задачи есть.

    На доске без активных задач это сэкономит два запроса на каждый поллинг.
    """
    has_active = any(
        task.status in eta_service.ACTIVE_STATUSES for task in _card_tasks(cards)
    )
    if not has_active:
        return {}
    return await eta_service.queue_forecast(db)


async def _load_card_with_tasks(
    card_id: str, db: AsyncSession, include_deleted: bool = False
) -> Optional[WorkflowCard]:
    conditions = [WorkflowCard.id == card_id]
    if not include_deleted:
        conditions.append(WorkflowCard.deleted_at.is_(None))
    stmt = (
        select(WorkflowCard)
        .where(*conditions)
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
    for attr in _STAGE_ATTRS:
        task = object.__getattribute__(card, attr)
        if task is not None and task.deleted_at is not None:
            object.__setattr__(card, attr, None)


async def _check_card_access(card: WorkflowCard, db: AsyncSession, current_user: dict) -> None:
    """Доступ к карточке определяется владельцем её проекта (у WorkflowCard нет owner_id)."""
    proj = await db.get(Project, card.project_id)
    if proj is None or not can_access(proj.owner_id, current_user, proj.is_shared):
        raise HTTPException(status_code=404, detail="Карточка не найдена")


@router.get("/projects/{project_id}/workflow-cards", response_model=list[WorkflowCardResponse])
async def get_workflow_cards(
    project_id: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    proj = await db.get(Project, project_id)
    if proj is None or not can_access(proj.owner_id, current_user, proj.is_shared):
        raise HTTPException(status_code=404, detail="Проект не найден")

    stmt = (
        select(WorkflowCard)
        .where(WorkflowCard.project_id == project_id, WorkflowCard.deleted_at.is_(None))
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
    forecast = await _card_forecast(db, list(cards))
    usage = await _cards_usage(db, list(cards))
    payload = [_build_card_response(c, forecast, usage) for c in cards]

    # ETag: этот список поллится каждые 5с. Если данные не изменились — отдаём 304
    # без тела (клиент отдаёт из кэша). Cache-Control private — данные за авторизацией.
    body = json.dumps(
        [p.model_dump(mode="json") for p in payload], ensure_ascii=False, sort_keys=True
    ).encode()
    etag = '"' + hashlib.md5(body).hexdigest() + '"'
    cache_headers = {"ETag": etag, "Cache-Control": "private, max-age=5"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=cache_headers)
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=5"
    return payload


@router.post("/projects/{project_id}/workflow-cards", response_model=WorkflowCardResponse, status_code=201)
async def create_workflow_card(
    project_id: str,
    body: WorkflowCardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    proj = await db.get(Project, project_id)
    if proj is None or not can_access(proj.owner_id, current_user, proj.is_shared):
        raise HTTPException(status_code=404, detail="Проект не найден")

    card = WorkflowCard(
        id=str(uuid.uuid4()),
        project_id=project_id,
        name=body.name,
        stage=body.stage,
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
    await _check_card_access(card, db, current_user)

    if body.name is not None:
        card.name = body.name
    if body.stage is not None:
        card.stage = body.stage

    card.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(card)

    # Перезагружаем с task-relationship после commit
    card = await _load_card_with_tasks(card_id, db)
    return _build_card_response(
        card, await _card_forecast(db, [card]), await _cards_usage(db, [card])
    )


@router.delete("/workflow-cards/{card_id}", status_code=204)
async def delete_workflow_card(
    card_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Soft delete: перемещает карточку и её задачи в корзину."""
    result = await db.execute(
        select(WorkflowCard).where(WorkflowCard.id == card_id, WorkflowCard.deleted_at.is_(None))
    )
    card = result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    await _check_card_access(card, db, current_user)

    now = datetime.now(timezone.utc)
    card.deleted_at = now

    task_ids = [tid for tid in [
        card.list_task_id,
        card.completeness_task_id,
        card.estimate_task_id,
        card.optimization_task_id,
    ] if tid is not None]
    for task_id in task_ids:
        task = await db.get(Task, task_id)
        if task is not None and task.deleted_at is None:
            task.deleted_at = now

    await db.commit()
    logger.info("WorkflowCard soft-deleted", card_id=card_id, task_count=len(task_ids))


class TrashCardItem(BaseModel):
    id: str
    name: str
    stage: str
    project_id: str
    project_name: str
    deleted_at: str
    task_count: int


class TrashCardsResponse(BaseModel):
    items: list[TrashCardItem]
    total: int


@router.get("/workflow-cards/trash", response_model=TrashCardsResponse)
async def get_trash_cards(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Список soft-deleted карточек текущего пользователя."""
    stmt = (
        select(WorkflowCard)
        .where(WorkflowCard.deleted_at.is_not(None))
        .order_by(WorkflowCard.deleted_at.desc())
    )
    result = await db.execute(stmt)
    cards = result.scalars().all()

    items = []
    for card in cards:
        proj = await db.get(Project, card.project_id)
        if not proj or not can_access(proj.owner_id, current_user, proj.is_shared):
            continue
        task_count = sum(1 for tid in [
            card.list_task_id,
            card.completeness_task_id,
            card.estimate_task_id,
            card.optimization_task_id,
        ] if tid is not None)
        items.append(TrashCardItem(
            id=card.id,
            name=card.name,
            stage=card.stage,
            project_id=card.project_id,
            project_name=proj.name if proj else "—",
            deleted_at=card.deleted_at.isoformat(),
            task_count=task_count,
        ))

    return TrashCardsResponse(items=items, total=len(items))


@router.post("/workflow-cards/{card_id}/restore", status_code=200)
async def restore_workflow_card(
    card_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Восстанавливает карточку из корзины в исходную стадию канбана."""
    result = await db.execute(
        select(WorkflowCard).where(WorkflowCard.id == card_id, WorkflowCard.deleted_at.is_not(None))
    )
    card = result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена в корзине")

    proj = await db.get(Project, card.project_id)
    if proj is None or not can_access(proj.owner_id, current_user, proj.is_shared):
        raise HTTPException(status_code=404, detail="Карточка не найдена в корзине")
    if proj.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Проект удалён — восстановление невозможно")

    card.deleted_at = None

    task_ids = [tid for tid in [
        card.list_task_id,
        card.completeness_task_id,
        card.estimate_task_id,
        card.optimization_task_id,
    ] if tid is not None]
    for task_id in task_ids:
        task = await db.get(Task, task_id)
        if task is not None and task.deleted_at is not None:
            task.deleted_at = None

    await db.commit()
    logger.info("WorkflowCard restored", card_id=card_id)
    return {"ok": True}


@router.delete("/workflow-cards/{card_id}/permanent", status_code=204)
async def permanent_delete_workflow_card(
    card_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Перманентное удаление карточки и всех её задач из БД."""
    result = await db.execute(
        select(WorkflowCard).where(WorkflowCard.id == card_id, WorkflowCard.deleted_at.is_not(None))
    )
    card = result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена в корзине")
    await _check_card_access(card, db, current_user)

    task_ids = [tid for tid in [
        card.list_task_id,
        card.completeness_task_id,
        card.estimate_task_id,
        card.optimization_task_id,
    ] if tid is not None]
    for task_id in task_ids:
        task = await db.get(Task, task_id)
        if task is not None:
            await db.delete(task)

    await db.flush()
    await db.delete(card)
    await db.commit()
    logger.info("WorkflowCard permanently deleted", card_id=card_id, task_count=len(task_ids))


class _PrimaryVersionBody(BaseModel):
    version_id: Optional[str] = None


@router.patch("/workflow-cards/{card_id}/primary-version", response_model=WorkflowCardResponse)
async def set_primary_version(
    card_id: str,
    body: _PrimaryVersionBody,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Устанавливает или сбрасывает главную версию сметы для карточки раздела."""
    from app.models.estimate_version import EstimateVersion

    result = await db.execute(select(WorkflowCard).where(WorkflowCard.id == card_id))
    card = result.scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    await _check_card_access(card, db, current_user)

    if body.version_id is not None:
        ver = await db.get(EstimateVersion, body.version_id)
        if ver is None:
            raise HTTPException(status_code=404, detail="Версия сметы не найдена")
        # Версия должна принадлежать доступной задаче — не ссылаемся на чужую.
        ver_task = await db.get(Task, ver.task_id)
        if ver_task is None or not can_access(ver_task.owner_id, current_user, ver_task.is_shared):
            raise HTTPException(status_code=404, detail="Версия сметы не найдена")

    card.primary_version_id = body.version_id
    card.updated_at = datetime.now(timezone.utc)
    await db.commit()

    updated = await _load_card_with_tasks(card_id, db)
    return _build_card_response(updated, None, await _cards_usage(db, [updated]))


async def _build_stage_meta(task: Optional[Task], db: AsyncSession) -> Optional[StageDetail]:
    """Метаданные файлов этапа без загрузки binary (использует size_bytes из колонки)."""
    if task is None:
        return None

    inp_rows = await db.execute(
        select(TaskInputFile)
        .where(TaskInputFile.task_id == task.id)
        .order_by(TaskInputFile.file_index)
    )
    inp_files = [
        InputFileDetail(
            index=r.file_index,
            name=r.file_name,
            size_bytes=r.size_bytes,
            mime_type=r.mime_type,
        )
        for r in inp_rows.scalars().all()
    ]

    res_rows = await db.execute(
        select(TaskResult)
        .where(TaskResult.task_id == task.id)
        .order_by(TaskResult.id)
    )
    res_files = [
        ResultFileDetail(
            result_id=r.id,
            slot=r.slot,
            file_name=r.file_name,
            size_bytes=r.size_bytes,
            mime_type=r.mime_type,
            created_at=r.created_at.isoformat(),
        )
        for r in res_rows.scalars().all()
    ]

    return StageDetail(
        task_id=str(task.id),
        task_type=task.task_type,
        task_status=task.status,
        task_name=task.name,
        task_created_at=task.created_at.isoformat(),
        manually_edited_at=task.manually_edited_at.isoformat() if task.manually_edited_at else None,
        input_files=inp_files,
        result_files=res_files,
    )


@router.get("/workflow-cards/{card_id}/detail", response_model=CardDetailResponse)
async def get_card_detail(
    card_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Детали карточки: метаданные файлов каждого этапа пайплайна."""
    card = await _load_card_with_tasks(card_id, db)
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    await _check_card_access(card, db, current_user)

    return CardDetailResponse(
        id=str(card.id),
        project_id=str(card.project_id),
        name=card.name,
        stage=card.stage,
        source_stage=await _build_stage_meta(card.list_task, db),
        completeness_stage=await _build_stage_meta(card.completeness_task, db),
        estimate_stage=await _build_stage_meta(card.estimate_task, db),
        optimization_stage=await _build_stage_meta(card.optimization_task, db),
    )


@router.get("/workflow-cards/{card_id}/files-meta", response_model=CardDetailResponse)
async def get_card_files_meta(
    card_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Лёгкий endpoint для канбан-карточек: метаданные файлов без binary-данных."""
    card = await _load_card_with_tasks(card_id, db)
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    await _check_card_access(card, db, current_user)

    return CardDetailResponse(
        id=str(card.id),
        project_id=str(card.project_id),
        name=card.name,
        stage=card.stage,
        source_stage=await _build_stage_meta(card.list_task, db),
        completeness_stage=await _build_stage_meta(card.completeness_task, db),
        estimate_stage=await _build_stage_meta(card.estimate_task, db),
        optimization_stage=await _build_stage_meta(card.optimization_task, db),
    )


@router.post("/workflow-cards/{card_id}/start-task", response_model=WorkflowCardResponse)
async def start_task(
    card_id: str,
    background_tasks: BackgroundTasks,
    task_type: str = Form(...),
    source_stage: Optional[int] = Form(None),
    use_previous_stage: Optional[bool] = Form(None),
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Атомарно создаёт задачу и привязывает её к карточке в одной транзакции."""
    from app.routers.tasks import _enqueue_task

    card = await _load_card_with_tasks(card_id, db)
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    await _check_card_access(card, db, current_user)

    field_name = _TASK_TYPE_TO_FIELD.get(task_type)
    if field_name is None:
        raise HTTPException(status_code=400, detail=f"Неизвестный task_type: {task_type}")

    estimation_status = "unestimated" if task_type in ESTIMATE_TASK_TYPES else "not_applicable"
    user_role = current_user.get("role", "user")

    # --- Подготовка файлов и user_prompt ---
    input_files_meta: list[dict] = []
    raw_files_bytes: list[bytes] = []
    resolved_prompt: Optional[str] = None
    # Задача, из перечня которой берётся объём работы (позиции точнее строк файла).
    volume_source_task_id: Optional[str] = None

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
        volume_source_task_id = str(src_task_id)

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
        estimate_bytes = await storage_service.load_bytes(tr.storage_key)
        raw_files_bytes = [estimate_bytes]
        input_files_meta = [
            {"name": tr.file_name, "mime_type": tr.mime_type, "size_bytes": len(estimate_bytes)}
        ]

    elif task_type in _COMPLETENESS_TYPES:
        # Источник — list_task
        if not card.list_task_id:
            raise HTTPException(
                status_code=400,
                detail="Для проверки полноты необходим завершённый Перечень",
            )
        resolved_prompt = card.list_task_id
        volume_source_task_id = str(card.list_task_id)

    elif files:
        # Загрузка одного или нескольких файлов (LIST_FROM_GRAND, LIST_FROM_PROJECT, ESTIMATE_OPTIMIZATION)
        for upload in files:
            content = await upload.read()
            mime = (upload.content_type or "application/octet-stream").split(";")[0].strip()
            raw_files_bytes.append(content)
            input_files_meta.append(
                {"name": upload.filename or "file", "mime_type": mime, "size_bytes": len(content)}
            )

    # Объём работы — пока файлы в памяти. Он же основа прогноза времени в очереди.
    volume_units, volume_kind = await eta_service.measure_task_volume(
        db,
        files=[
            (meta["mime_type"], meta["name"], raw)
            for meta, raw in zip(input_files_meta, raw_files_bytes)
        ],
        source_task_id=volume_source_task_id,
    )

    # --- Атомарная транзакция: создать Task + обновить карточку ---
    task_id = str(uuid.uuid4())
    new_task = Task(
        id=task_id,
        user_role=user_role,
        owner_id=current_user_id(current_user),
        task_type=task_type,
        status="pending",
        input_files=input_files_meta,
        input_file_data=input_files_meta,
        user_prompt=resolved_prompt,
        chat_history=[],
        estimation_status=estimation_status,
        project_id=card.project_id,
        volume_units=volume_units,
        volume_kind=volume_kind,
    )
    db.add(new_task)
    await db.flush()  # получаем task.id, не коммитим

    # Сохраняем все файлы в task_input_files
    for idx, (file_bytes, meta) in enumerate(zip(raw_files_bytes, input_files_meta)):
        storage_key = await storage_service.store_input_file(
            task_id, idx, meta["name"], meta["mime_type"], file_bytes
        )
        db.add(TaskInputFile(
            task_id=task_id,
            file_index=idx,
            file_name=meta["name"],
            mime_type=meta["mime_type"],
            size_bytes=meta["size_bytes"],
            storage_key=storage_key,
        ))

    # Привязываем задачу к карточке
    setattr(card, field_name, task_id)
    card.updated_at = datetime.now(timezone.utc)

    await db.commit()  # единый commit — при ошибке rollback оба изменения

    logger.info("start-task atomic commit", card_id=card_id, task_id=task_id, task_type=task_type)

    # Ставим задачу в durable-очередь после commit — исполнит worker.
    await _enqueue_task(db, task_id)

    # Возвращаем обновлённую карточку
    updated_card = await _load_card_with_tasks(card_id, db)
    return _build_card_response(
        updated_card,
        await _card_forecast(db, [updated_card]),
        await _cards_usage(db, [updated_card]),
    )

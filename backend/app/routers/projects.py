import io
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, delete
from datetime import datetime, timezone
import structlog

from app.database import get_db
from app.models.project import Project
from app.models.task import Task
from app.models.result import TaskResult
from app.models.summary_estimate import SummaryEstimate
from app.models.user import User
from app.utils.auth import get_current_user, get_admin_user, current_user_id
from app.utils.owner_names import owner_names as _owner_names
from app.utils.permissions import (
    visibility_filter,
    can_access,
    get_manager_user,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    # Проценты доп. расходов проекта. Раньше 3% были зашиты в генераторе файла
    # сметы; теперь это настройка, и её значение подставляется во все документы
    # проекта. Отрицательная ставка и ставка больше 100% — заведомая ошибка
    # ввода, поэтому отклоняются, а не сохраняются молча.
    overhead_pct: Optional[float] = Field(default=None, ge=0, le=100)
    transport_pct: Optional[float] = Field(default=None, ge=0, le=100)


class ArchiveRequest(BaseModel):
    archived: bool


class OwnerRequest(BaseModel):
    owner_id: int


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str
    is_archived: bool = False
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    overhead_pct: float = 3.0
    transport_pct: float = 3.0


class ProjectCardResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str
    unestimated: int
    estimated: int
    optimized: int
    other: int
    total_cost: Optional[float]
    optimized_cost: Optional[float] = None
    summary_total: Optional[float] = None
    task_type_counts: dict[str, int] = {}
    total_tasks: int = 0
    is_archived: bool = False
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None


class TaskBrief(BaseModel):
    id: str
    task_type: str
    status: str
    estimation_status: str
    cost: Optional[float]
    created_at: str
    source_file_name: Optional[str] = None
    slot_files: dict[str, str] = {}
    name: Optional[str] = None
    deleted_at: Optional[str] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None  # ответственный (текущий владелец задачи)


class ProjectDetailResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str
    unestimated: int
    estimated: int
    optimized: int
    other: int
    total_cost: Optional[float]
    optimized_cost: Optional[float] = None
    summary_total: Optional[float] = None
    has_summary: bool = False
    task_type_counts: dict[str, int] = {}
    total_tasks: int = 0
    is_archived: bool = False
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    tasks: list[TaskBrief]


class TrashProjectItem(BaseModel):
    id: str
    name: str
    description: Optional[str]
    created_at: str
    deleted_at: str
    owner_name: Optional[str] = None


class TrashProjectsResponse(BaseModel):
    items: list[TrashProjectItem]
    total: int


def _project_to_response(p: Project, owner_name: Optional[str] = None) -> ProjectResponse:
    return ProjectResponse(
        id=str(p.id),
        name=p.name,
        description=p.description,
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
        is_archived=p.is_archived,
        owner_id=p.owner_id,
        owner_name=owner_name,
        overhead_pct=float(p.overhead_pct if p.overhead_pct is not None else 3),
        transport_pct=float(p.transport_pct if p.transport_pct is not None else 3),
    )


async def _get_project_or_404(
    project_id: str, db: AsyncSession, current_user: Optional[dict] = None
) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id, Project.deleted_at.is_(None)))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    # Изоляция по владельцу: чужой проект для ПМ = 404 (не раскрываем существование).
    if current_user is not None and not can_access(project.owner_id, current_user, project.is_shared):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    return project


async def _aggregate(project_id: str, db: AsyncSession) -> dict:
    stmt = select(
        func.count(case((Task.estimation_status == "unestimated", 1), else_=None)).label("unestimated"),
        func.count(case((Task.estimation_status == "estimated", 1), else_=None)).label("estimated"),
        func.count(case((Task.estimation_status == "optimized", 1), else_=None)).label("optimized"),
        func.count(case((Task.estimation_status == "not_applicable", 1), else_=None)).label("other"),
        func.sum(
            case(
                (Task.estimation_status.in_(["estimated", "optimized"]), Task.cost),
                else_=None,
            )
        ).label("total_cost"),
        func.sum(
            case(
                (Task.estimation_status == "optimized", Task.cost),
                else_=None,
            )
        ).label("optimized_cost"),
    ).where(Task.project_id == project_id, Task.deleted_at.is_(None))
    row = (await db.execute(stmt)).one()
    return {
        "unestimated": row.unestimated or 0,
        "estimated": row.estimated or 0,
        "optimized": row.optimized or 0,
        "other": row.other or 0,
        "total_cost": float(row.total_cost) if row.total_cost is not None else None,
        "optimized_cost": float(row.optimized_cost) if row.optimized_cost is not None else None,
    }


async def _get_task_type_counts(project_ids: list[str], db: AsyncSession) -> dict[str, dict[str, int]]:
    """Возвращает {project_id: {task_type: count}}"""
    if not project_ids:
        return {}
    stmt = (
        select(Task.project_id, Task.task_type, func.count().label("cnt"))
        .where(Task.project_id.in_(project_ids), Task.deleted_at.is_(None))
        .group_by(Task.project_id, Task.task_type)
    )
    rows = (await db.execute(stmt)).all()
    result: dict[str, dict[str, int]] = {}
    for row in rows:
        pid = str(row.project_id)
        result.setdefault(pid, {})[row.task_type] = row.cnt
    return result


@router.post("", response_model=ProjectResponse)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    project = Project(
        id=str(uuid.uuid4()),
        name=body.name,
        description=body.description,
        owner_id=current_user_id(current_user),
    )
    db.add(project)
    await db.commit()
    logger.info(
        "Project created",
        project_id=str(project.id), name=project.name, owner_id=project.owner_id,
    )
    return _project_to_response(project)


@router.get("", response_model=list[ProjectCardResponse])
async def list_projects(
    archived: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    vis = visibility_filter(Project, current_user)
    stmt = (
        select(
            Project.id,
            Project.name,
            Project.description,
            Project.created_at,
            Project.updated_at,
            Project.summary_total,
            Project.is_archived,
            Project.owner_id,
            func.count(case((Task.estimation_status == "unestimated", 1), else_=None)).label("unestimated"),
            func.count(case((Task.estimation_status == "estimated", 1), else_=None)).label("estimated"),
            func.count(case((Task.estimation_status == "optimized", 1), else_=None)).label("optimized"),
            func.count(case((Task.estimation_status == "not_applicable", 1), else_=None)).label("other"),
            func.count(Task.id).label("total_tasks"),
            func.sum(
                case(
                    (Task.estimation_status.in_(["estimated", "optimized"]), Task.cost),
                    else_=None,
                )
            ).label("total_cost"),
            func.sum(
                case(
                    (Task.estimation_status == "optimized", Task.cost),
                    else_=None,
                )
            ).label("optimized_cost"),
        )
        .outerjoin(Task, (Task.project_id == Project.id) & Task.deleted_at.is_(None))
        .where(
            Project.deleted_at.is_(None),
            Project.is_archived.is_(True) if archived else Project.is_archived.is_(False),
            *( [vis] if vis is not None else [] ),
        )
        .group_by(
            Project.id,
            Project.name,
            Project.description,
            Project.created_at,
            Project.updated_at,
            Project.summary_total,
            Project.is_archived,
            Project.owner_id,
        )
        .order_by(Project.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    project_ids = [str(row.id) for row in rows]
    type_counts = await _get_task_type_counts(project_ids, db)
    owner_names = await _owner_names([row.owner_id for row in rows], db)

    return [
        ProjectCardResponse(
            id=str(row.id),
            name=row.name,
            description=row.description,
            created_at=row.created_at.isoformat(),
            updated_at=row.updated_at.isoformat(),
            is_archived=row.is_archived,
            owner_id=row.owner_id,
            owner_name=owner_names.get(row.owner_id),
            unestimated=row.unestimated or 0,
            estimated=row.estimated or 0,
            optimized=row.optimized or 0,
            other=row.other or 0,
            total_tasks=row.total_tasks or 0,
            summary_total=float(row.summary_total) if row.summary_total is not None else None,
            total_cost=(
                float(row.summary_total)
                if row.summary_total is not None
                else (float(row.total_cost) if row.total_cost is not None else None)
            ),
            optimized_cost=float(row.optimized_cost) if row.optimized_cost is not None else None,
            task_type_counts=type_counts.get(str(row.id), {}),
        )
        for row in rows
    ]


@router.get("/unassigned", response_model=list[TaskBrief])
async def list_unassigned_tasks(
    archived: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    vis = visibility_filter(Task, current_user)
    tasks_result = await db.execute(
        select(
            Task.id, Task.task_type, Task.status, Task.estimation_status,
            Task.cost, Task.created_at, Task.input_files, Task.name, Task.deleted_at,
            Task.owner_id,
        ).where(
            Task.project_id.is_(None), Task.deleted_at.is_(None),
            Task.is_archived.is_(True) if archived else Task.is_archived.is_(False),
            *( [vis] if vis is not None else [] ),
        ).order_by(Task.created_at.desc())
    )
    rows = tasks_result.all()
    owner_names = await _owner_names([row.owner_id for row in rows], db)
    return [
        TaskBrief(
            id=str(row.id),
            task_type=row.task_type,
            status=row.status,
            estimation_status=row.estimation_status,
            cost=float(row.cost) if row.cost is not None else None,
            created_at=row.created_at.isoformat(),
            source_file_name=(row.input_files[0]["name"] if row.input_files else None),
            name=row.name,
            deleted_at=row.deleted_at.isoformat() if row.deleted_at else None,
            owner_id=row.owner_id,
            owner_name=owner_names.get(row.owner_id),
        )
        for row in rows
    ]


@router.get("/trash", response_model=TrashProjectsResponse)
async def list_trash_projects(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Список удалённых проектов (корзина). Общая: видно, чей проект удалён."""
    vis = visibility_filter(Project, current_user)
    vis_clause = [vis] if vis is not None else []
    count_result = await db.execute(
        select(func.count(Project.id)).where(Project.deleted_at.is_not(None), *vis_clause)
    )
    total = count_result.scalar() or 0

    data_result = await db.execute(
        select(
            Project.id, Project.name, Project.description, Project.created_at,
            Project.deleted_at, Project.owner_id,
        )
        .where(Project.deleted_at.is_not(None), *vis_clause)
        .order_by(Project.deleted_at.desc())
    )
    rows = data_result.all()
    names = await _owner_names([row.owner_id for row in rows], db)

    items = [
        TrashProjectItem(
            id=str(row.id),
            name=row.name,
            description=row.description,
            created_at=row.created_at.isoformat(),
            deleted_at=row.deleted_at.isoformat(),
            owner_name=names.get(row.owner_id),
        )
        for row in rows
    ]
    return TrashProjectsResponse(items=items, total=total)


@router.delete("/trash", status_code=status.HTTP_204_NO_CONTENT)
async def clear_project_trash(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_admin_user),
):
    """Удалить все проекты из корзины навсегда (только для администраторов)."""
    await db.execute(delete(Project).where(Project.deleted_at.is_not(None)))
    await db.commit()
    logger.info("Project trash cleared")


@router.get("/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    project = await _get_project_or_404(project_id, db, current_user)
    agg = await _aggregate(project_id, db)

    # Read summary state directly from SummaryEstimate (source of truth)
    summary_res = await db.execute(
        select(SummaryEstimate.id, SummaryEstimate.total_for_customer)
        .where(SummaryEstimate.project_id == project_id)
    )
    summary_row = summary_res.one_or_none()
    has_summary = summary_row is not None
    if has_summary and summary_row.total_for_customer:
        summary_total = float(summary_row.total_for_customer)
        agg["total_cost"] = summary_total
    else:
        summary_total = 0.0 if has_summary else None

    tasks_result = await db.execute(
        select(
            Task.id, Task.task_type, Task.status, Task.estimation_status,
            Task.cost, Task.created_at, Task.input_files, Task.name, Task.deleted_at,
            Task.owner_id,
        ).where(Task.project_id == project_id, Task.deleted_at.is_(None)).order_by(Task.created_at.desc())
    )
    tasks = tasks_result.all()

    slot_files_by_task: dict[str, dict[str, str]] = {}
    task_ids = [str(t.id) for t in tasks]
    if task_ids:
        slots_res = await db.execute(
            select(TaskResult.task_id, TaskResult.slot, TaskResult.file_name).where(
                TaskResult.task_id.in_(task_ids),
                TaskResult.slot.in_(["estimate", "optimized"]),
            )
        )
        for row in slots_res.all():
            tid = str(row.task_id)
            slot_files_by_task.setdefault(tid, {})[row.slot] = row.file_name

    type_counts = await _get_task_type_counts([project_id], db)
    owner_names = await _owner_names([project.owner_id] + [t.owner_id for t in tasks], db)

    return ProjectDetailResponse(
        id=str(project.id),
        name=project.name,
        description=project.description,
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
        is_archived=project.is_archived,
        owner_id=project.owner_id,
        owner_name=owner_names.get(project.owner_id),
        summary_total=summary_total,
        has_summary=has_summary,
        task_type_counts=type_counts.get(project_id, {}),
        total_tasks=len(tasks),
        tasks=[
            TaskBrief(
                id=str(t.id),
                task_type=t.task_type,
                status=t.status,
                estimation_status=t.estimation_status,
                cost=float(t.cost) if t.cost is not None else None,
                created_at=t.created_at.isoformat(),
                source_file_name=(t.input_files[0]["name"] if t.input_files else None),
                slot_files=slot_files_by_task.get(str(t.id), {}),
                name=t.name,
                deleted_at=t.deleted_at.isoformat() if t.deleted_at else None,
                owner_id=t.owner_id,
                owner_name=owner_names.get(t.owner_id),
            )
            for t in tasks
        ],
        **agg,
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    project = await _get_project_or_404(project_id, db, current_user)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description

    percentages_changed = (
        (body.overhead_pct is not None
         and float(body.overhead_pct) != float(project.overhead_pct or 0))
        or (body.transport_pct is not None
            and float(body.transport_pct) != float(project.transport_pct or 0))
    )
    if body.overhead_pct is not None:
        project.overhead_pct = body.overhead_pct
    if body.transport_pct is not None:
        project.transport_pct = body.transport_pct

    project.updated_at = datetime.now(timezone.utc)
    await db.commit()

    if percentages_changed:
        await _recalculate_project_estimates(project_id, db)

    return _project_to_response(project)


async def _recalculate_project_estimates(project_id: str, db: AsyncSession) -> None:
    """Пересобрать сметы проекта после смены ставок доп. расходов.

    Итоги на экране считаются на лету и меняются сразу, а вот `task.cost` и
    скачиваемый файл — нет. Без пересчёта карточка проекта, дашборд и воронка
    показывали бы сумму по старым ставкам, и человек увидел бы два разных числа
    за одно и то же. Смет в проекте единицы, поэтому пересчёт прямой.
    """
    from app.services import estimate_store

    res = await db.execute(
        select(Task).where(
            Task.project_id == project_id,
            Task.task_type == "ESTIMATE_FROM_LIST",
            Task.deleted_at.is_(None),
        )
    )
    recalculated = 0
    for task in res.scalars().all():
        version = await estimate_store.get_working_version(db, str(task.id))
        if version is None or not version.rows:
            continue
        await estimate_store.sync_artifacts(db, task, version.rows, version)
        recalculated += 1

    if recalculated:
        await db.commit()
    logger.info(
        "project_percentages_applied", project_id=project_id, estimates=recalculated,
    )


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    project = await _get_project_or_404(project_id, db, current_user)
    project.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("Project soft-deleted (moved to trash)", project_id=project_id)
    return {"project_id": project_id, "status": "deleted"}


@router.post("/{project_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Восстановить проект из корзины."""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_not(None))
    )
    project = result.scalar_one_or_none()
    if not project or not can_access(project.owner_id, current_user, project.is_shared):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден или не удалён")
    project.deleted_at = None
    await db.commit()
    logger.info("Project restored from trash", project_id=project_id)


@router.delete("/{project_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def permanent_delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_admin_user),
):
    """Окончательное удаление проекта (только для администраторов)."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Проект не найден")
    await db.delete(project)
    await db.commit()
    logger.info("Project permanently deleted", project_id=project_id)


@router.get("/{project_id}/export")
async def export_project(
    project_id: str,
    format: str = "xlsx",
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if format not in ("xlsx", "pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Параметр format должен быть xlsx или pdf",
        )

    project = await _get_project_or_404(project_id, db, current_user)

    tasks_result = await db.execute(
        select(Task).where(Task.project_id == project_id).order_by(Task.created_at.asc())
    )
    tasks = list(tasks_result.scalars().all())

    slot_results: dict = {"source": [], "estimate": [], "optimized": []}
    if tasks:
        task_ids = [t.id for t in tasks]
        results_stmt = await db.execute(
            select(TaskResult).where(
                TaskResult.task_id.in_(task_ids),
                TaskResult.slot.in_(["source", "estimate", "optimized"]),
            )
        )
        task_results = list(results_stmt.scalars().all())
        task_map = {t.id: t for t in tasks}
        for tr in task_results:
            if tr.task_id in task_map:
                slot_results[tr.slot].append((task_map[tr.task_id], tr))

    base_url = str(request.base_url).rstrip("/") if request else ""

    from urllib.parse import quote

    if format == "xlsx":
        from app.utils.xlsx_exporter import generate_project_xlsx
        file_bytes = generate_project_xlsx(project, tasks, slot_results, base_url)
        safe_name = project.name.replace('"', '').replace('/', '-')
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"{safe_name}.xlsx"
    else:
        from app.utils.pdf_exporter import generate_project_pdf
        file_bytes = generate_project_pdf(project, tasks, slot_results, base_url)
        safe_name = project.name.replace('"', '').replace('/', '-')
        media_type = "application/pdf"
        filename = f"{safe_name}.pdf"

    encoded_filename = quote(filename, safe="")
    content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}"

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=media_type,
        headers={"Content-Disposition": content_disposition},
    )


@router.patch("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    project_id: str,
    body: ArchiveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Переместить проект в архив / вернуть из архива. Право = право редактирования."""
    project = await _get_project_or_404(project_id, db, current_user)
    project.is_archived = body.archived
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("Project archive toggled", project_id=project_id, archived=body.archived)
    return _project_to_response(project)


@router.patch("/{project_id}/owner", response_model=ProjectResponse)
async def reassign_project_owner(
    project_id: str,
    body: OwnerRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_manager_user),
):
    """Переназначить владельца проекта (только руководитель/админ)."""
    project = await _get_project_or_404(project_id, db)
    owner = (
        await db.execute(select(User).where(User.id == body.owner_id))
    ).scalar_one_or_none()
    if not owner or not owner.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Указан несуществующий или неактивный пользователь",
        )
    project.owner_id = body.owner_id
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("Project owner reassigned", project_id=project_id, owner_id=body.owner_id)
    return _project_to_response(project, owner_name=(owner.full_name or owner.username))

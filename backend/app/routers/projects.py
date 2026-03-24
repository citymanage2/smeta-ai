"""Projects router — CRUD for projects + estimate management."""
from typing import Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import structlog

from app.database import get_db, AsyncSessionLocal
from app.models.project import Project
from app.models.task import Task
from app.models.task_version import TaskVersion
from app.models.estimate_item import EstimateItem
from app.utils.auth import get_current_user
from app.services import snapshot_service
from app.services import optimization_service
from app.services import analogue_service

logger = structlog.get_logger()

router = APIRouter(prefix="/projects", tags=["projects"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    created_at: str
    updated_at: str
    tasks_count: int = 0


class TaskSummary(BaseModel):
    id: str
    task_type: str
    status: str
    estimate_status: str
    estimate_status_updated_by: str
    estimate_status_updated_at: Optional[str]
    created_at: str
    updated_at: str
    input_files: list
    project_id: Optional[str]


class EstimateStatusUpdate(BaseModel):
    status: str   # 'uploaded' | 'calculated' | 'optimized'
    updated_by: str = "manual"  # 'manual' | 'auto'


class OptimizePlanRequest(BaseModel):
    optimize_materials: bool = True
    optimize_works: bool = True
    optimize_other: bool = False
    custom_prompt: Optional[str] = None


class OptimizeExecuteRequest(OptimizePlanRequest):
    confirmed: bool = False


class FindAnaloguesResponse(BaseModel):
    item_id: str
    original: dict
    analogues: list


class ApplyAnalogueRequest(BaseModel):
    analogue_name: str
    analogue_price: float
    analogue_note: str = ""
    supplier: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

VALID_ESTIMATE_STATUSES = {"uploaded", "calculated", "optimized"}


def _task_to_summary(task: Task) -> TaskSummary:
    return TaskSummary(
        id=str(task.id),
        task_type=task.task_type,
        status=task.status,
        estimate_status=task.estimate_status,
        estimate_status_updated_by=task.estimate_status_updated_by,
        estimate_status_updated_at=(
            task.estimate_status_updated_at.isoformat()
            if task.estimate_status_updated_at else None
        ),
        created_at=task.created_at.isoformat(),
        updated_at=task.updated_at.isoformat(),
        input_files=task.input_files or [],
        project_id=str(task.project_id) if task.project_id else None,
    )


# ── Project CRUD ──────────────────────────────────────────────────────────────

@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    project = Project(
        name=body.name,
        description=body.description,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    logger.info("Project created", project_id=str(project.id), name=project.name)
    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        description=project.description,
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
        tasks_count=0,
    )


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    projects = result.scalars().all()

    # Count tasks per project
    counts_result = await db.execute(
        select(Task.project_id, func.count(Task.id).label("cnt"))
        .where(Task.project_id.isnot(None))
        .group_by(Task.project_id)
    )
    counts = {str(row.project_id): row.cnt for row in counts_result}

    return [
        ProjectResponse(
            id=str(p.id),
            name=p.name,
            description=p.description,
            created_at=p.created_at.isoformat(),
            updated_at=p.updated_at.isoformat(),
            tasks_count=counts.get(str(p.id), 0),
        )
        for p in projects
    ]


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")

    tasks_result = await db.execute(
        select(Task)
        .where(Task.project_id == project_id)
        .order_by(Task.created_at.desc())
    )
    tasks = tasks_result.scalars().all()

    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "tasks": [_task_to_summary(t).model_dump() for t in tasks],
    }


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")

    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    project.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(project)

    cnt_result = await db.execute(
        select(func.count(Task.id)).where(Task.project_id == project_id)
    )
    cnt = cnt_result.scalar() or 0

    return ProjectResponse(
        id=str(project.id),
        name=project.name,
        description=project.description,
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
        tasks_count=cnt,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")

    # Unlink tasks (do not delete them)
    tasks_result = await db.execute(
        select(Task).where(Task.project_id == project_id)
    )
    for task in tasks_result.scalars().all():
        task.project_id = None

    await db.delete(project)
    await db.commit()
    logger.info("Project deleted", project_id=project_id)


# ── Estimate management within projects ──────────────────────────────────────

@router.post("/{project_id}/estimates/{task_id}", status_code=status.HTTP_200_OK)
async def add_task_to_project(
    project_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    if not proj_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Проект не найден")

    task_result = await db.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    task.project_id = project_id
    await db.commit()
    return {"task_id": task_id, "project_id": project_id}


@router.delete("/{project_id}/estimates/{task_id}", status_code=status.HTTP_200_OK)
async def remove_task_from_project(
    project_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    task_result = await db.execute(
        select(Task).where(Task.id == task_id, Task.project_id == project_id)
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена в этом проекте")

    task.project_id = None
    await db.commit()
    return {"task_id": task_id, "project_id": None}


# ── Estimate status ───────────────────────────────────────────────────────────

@router.patch("/estimates/{task_id}/status")
async def update_estimate_status(
    task_id: str,
    body: EstimateStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if body.status not in VALID_ESTIMATE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый статус. Допустимые: {VALID_ESTIMATE_STATUSES}",
        )
    task_result = await db.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    task.estimate_status = body.status
    task.estimate_status_updated_at = datetime.now(timezone.utc)
    task.estimate_status_updated_by = body.updated_by
    await db.commit()
    return {
        "task_id": task_id,
        "estimate_status": task.estimate_status,
        "updated_by": task.estimate_status_updated_by,
    }


# ── Version history ───────────────────────────────────────────────────────────

@router.get("/estimates/{task_id}/versions")
async def list_versions(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(TaskVersion)
        .where(TaskVersion.task_id == task_id)
        .order_by(TaskVersion.version_number.desc())
    )
    versions = result.scalars().all()
    return [
        {
            "id": str(v.id),
            "task_id": str(v.task_id),
            "version_number": v.version_number,
            "change_description": v.change_description,
            "change_type": v.change_type,
            "created_at": v.created_at.isoformat(),
            "created_by": v.created_by,
            "items_count": len(v.snapshot.get("items", [])),
        }
        for v in versions
    ]


@router.post("/estimates/{task_id}/versions/{version_id}/restore")
async def restore_version(
    task_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        await snapshot_service.restore_snapshot(task_id, version_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"task_id": task_id, "restored_version": version_id}


# ── Estimate items ────────────────────────────────────────────────────────────

@router.get("/estimates/{task_id}/items")
async def list_estimate_items(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(EstimateItem)
        .where(EstimateItem.task_id == task_id)
        .order_by(EstimateItem.position)
    )
    items = result.scalars().all()
    return [
        {
            "id": item.id,
            "position": item.position,
            "type": item.type,
            "name": item.name,
            "unit": item.unit,
            "quantity": item.quantity,
            "work_price": item.work_price,
            "mat_price": item.mat_price,
            "section": item.section,
            "notes": item.notes,
            "is_analogue": item.is_analogue,
            "original_item_id": item.original_item_id,
            "analogue_note": item.analogue_note,
            "extra": item.extra or {},
        }
        for item in items
    ]


# ── Optimization ──────────────────────────────────────────────────────────────

async def _run_optimization_bg(task_id: str, request: OptimizeExecuteRequest) -> None:
    async with AsyncSessionLocal() as db:
        try:
            await optimization_service.execute_optimization(
                task_id=task_id,
                db=db,
                optimize_materials=request.optimize_materials,
                optimize_works=request.optimize_works,
                optimize_other=request.optimize_other,
                custom_prompt=request.custom_prompt,
            )
        except Exception as e:
            logger.error("Background optimization failed", task_id=task_id, error=str(e))


@router.post("/estimates/{task_id}/optimize/plan")
async def optimization_plan(
    task_id: str,
    body: OptimizePlanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        plan = await optimization_service.get_optimization_plan(
            task_id=task_id,
            db=db,
            optimize_materials=body.optimize_materials,
            optimize_works=body.optimize_works,
            optimize_other=body.optimize_other,
            custom_prompt=body.custom_prompt,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return plan


@router.post("/estimates/{task_id}/optimize/execute")
async def optimization_execute(
    task_id: str,
    body: OptimizeExecuteRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="Установите confirmed=true для запуска")

    # Mark task as 'processing optimization'
    task_result = await db.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    background_tasks.add_task(_run_optimization_bg, task_id, body)
    return {"task_id": task_id, "status": "optimization_started"}


# ── Analogues ─────────────────────────────────────────────────────────────────

async def _run_find_analogues_bg(task_id: str, item_id: str) -> None:
    """Background analogue search — result stored in item.extra['analogues']."""
    async with AsyncSessionLocal() as db:
        try:
            result = await analogue_service.find_analogues(task_id, item_id, db)
            # Cache found analogues in item.extra
            item_result = await db.execute(
                select(EstimateItem).where(EstimateItem.id == item_id)
            )
            item = item_result.scalar_one_or_none()
            if item:
                item.extra = {**(item.extra or {}), "analogues_cache": result.get("analogues", [])}
                await db.commit()
        except Exception as e:
            logger.error("Background analogue search failed", item_id=item_id, error=str(e))


@router.post("/estimates/{task_id}/items/{item_id}/find-analogues")
async def find_item_analogues(
    task_id: str,
    item_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Trigger async analogue search. Poll GET .../items to see cached result."""
    item_result = await db.execute(
        select(EstimateItem).where(
            EstimateItem.id == item_id,
            EstimateItem.task_id == task_id,
        )
    )
    item = item_result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Позиция не найдена")

    # Clear old cache
    item.extra = {k: v for k, v in (item.extra or {}).items() if k != "analogues_cache"}
    item.extra["analogues_searching"] = True
    await db.commit()

    background_tasks.add_task(_run_find_analogues_bg, task_id, item_id)
    return {"item_id": item_id, "status": "searching"}


@router.post("/estimates/{task_id}/items/{item_id}/apply-analogue")
async def apply_item_analogue(
    task_id: str,
    item_id: str,
    body: ApplyAnalogueRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = await analogue_service.apply_analogue(
            task_id=task_id,
            item_id=item_id,
            analogue_name=body.analogue_name,
            analogue_price=body.analogue_price,
            analogue_note=body.analogue_note,
            supplier=body.supplier,
            db=db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.post("/estimates/{task_id}/items/{item_id}/revert-analogue")
async def revert_item_analogue(
    task_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = await analogue_service.revert_analogue(task_id, item_id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result

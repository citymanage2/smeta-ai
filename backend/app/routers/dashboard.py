from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import DateTime, case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.api_call_log import ApiCallLog
from app.models.price import PriceMaterial, PriceWork
from app.models.price_list import PriceList
from app.models.project import Project
from app.models.task import Task
from app.schemas.eta import TaskEta
from app.services import eta_service
from app.utils.permissions import get_manager_user

logger = structlog.get_logger()

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

CHECK_TYPES = {"CHECK_LIST_COMPLETENESS", "CHECK_PROJECT_COMPLETENESS"}


# ── Response models ────────────────────────────────────────────────────────────


class PulseStats(BaseModel):
    created_today: int
    processing_now: int
    completed_today: int
    failed_today: int


class ActiveTask(BaseModel):
    id: str
    task_type: str
    status: str
    progress_message: Optional[str]
    created_at: str
    project_id: Optional[str]
    project_name: Optional[str]
    # Когда стартует и когда будет результат. None — прогноз построить не удалось.
    eta: Optional[TaskEta] = None


class FailedTask(BaseModel):
    id: str
    task_type: str
    error_message: Optional[str]
    created_at: str
    error_pattern: str


class FailedTaskGroup(BaseModel):
    pattern: str
    task_type: str
    count: int
    last_failed_at: str
    tasks: list[FailedTask]


class QualityFunnel(BaseModel):
    completed_count: int
    estimated_count: int
    manually_edited_count: int
    human_edit_rate: float


class TaskTypeBreakdown(BaseModel):
    list_from_grand: int
    list_from_project: int
    check_completeness: int
    estimate_from_list: int
    optimization: int


class ProjectCard(BaseModel):
    id: str
    name: str
    created_at: str
    total_cost: Optional[float]
    last_task_at: Optional[str]
    task_breakdown: TaskTypeBreakdown
    has_active: bool
    has_errors: bool


class ChartDay(BaseModel):
    date: str
    LIST_FROM_GRAND: int
    LIST_FROM_PROJECT: int
    CHECK_COMPLETENESS: int
    ESTIMATE_FROM_LIST: int
    ESTIMATE_OPTIMIZATION: int


class PriceListInfo(BaseModel):
    type: str
    updated_at: Optional[str]
    embedding_status: Optional[str]
    items_count: int


class ApiCostByTaskType(BaseModel):
    task_type: Optional[str]
    cost_usd: float
    calls_count: int


class ApiCosts(BaseModel):
    today_usd: float
    week_usd: float
    month_usd: float
    cache_hit_rate: float
    by_task_type: list[ApiCostByTaskType]


class DashboardStats(BaseModel):
    pulse: PulseStats
    active_queue: list[ActiveTask]
    errors: list[FailedTaskGroup]
    quality_funnel: QualityFunnel
    projects: list[ProjectCard]
    orphan_tasks_count: int
    task_chart: list[ChartDay]
    price_lists: list[PriceListInfo]
    api_costs: ApiCosts


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    response: Response,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_manager_user),
) -> DashboardStats:
    # Дашборд — управленческий раздел (очередь, ошибки, API-расходы, прайс-листы).
    # Доступ только руководителю/админу; ПМ работает из изолированных панелей.
    # HTTP-кэш в такт polling: несколько вкладок/компонентов, запросивших дашборд
    # в окне 10 с, получают ответ из кэша браузера, не нагружая БД повторно.
    # private — данные за авторизацией, не кэшировать на общих прокси.
    response.headers["Cache-Control"] = "private, max-age=10"
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # 1. Pulse — today's counters
    today_row = (
        await db.execute(
            select(
                func.count(Task.id).label("created_today"),
                func.count(case((Task.status == "completed", Task.id))).label("completed_today"),
                func.count(case((Task.status == "failed", Task.id))).label("failed_today"),
            ).where(
                Task.deleted_at.is_(None),
                Task.created_at >= today_start,
            )
        )
    ).one()

    processing_now = (
        await db.execute(
            select(func.count(Task.id)).where(
                Task.deleted_at.is_(None),
                Task.status == "processing",
            )
        )
    ).scalar_one()

    pulse = PulseStats(
        created_today=today_row.created_today,
        processing_now=processing_now,
        completed_today=today_row.completed_today,
        failed_today=today_row.failed_today,
    )

    # 2. Active queue (pending + processing)
    active_rows = (
        await db.execute(
            select(Task, Project.name.label("project_name"))
            .outerjoin(Project, Task.project_id == Project.id)
            .where(
                Task.deleted_at.is_(None),
                Task.status.in_(["pending", "processing"]),
            )
            .order_by(Task.created_at.asc())
        )
    ).all()

    # Прогноз считается разом по всей очереди: старт задачи зависит от всех,
    # кто впереди неё. Задачи уже загружены — второй раз их не читаем.
    forecast = await eta_service.queue_forecast(
        db, active_tasks=[t for t, _ in active_rows], now=now
    )

    active_queue = [
        ActiveTask(
            id=str(t.id),
            task_type=t.task_type,
            status=t.status,
            progress_message=t.progress_message,
            created_at=t.created_at.isoformat(),
            project_id=str(t.project_id) if t.project_id else None,
            project_name=pname,
            eta=forecast.get(str(t.id)),
        )
        for t, pname in active_rows
    ]

    # 3. Failed tasks — last 7 days, grouped by error pattern + task_type
    seven_days_ago = now - timedelta(days=7)
    failed_tasks = (
        await db.execute(
            select(Task)
            .where(
                Task.deleted_at.is_(None),
                Task.status == "failed",
                Task.created_at >= seven_days_ago,
            )
            .order_by(Task.created_at.desc())
        )
    ).scalars().all()

    groups: dict[tuple, dict] = {}
    for t in failed_tasks:
        raw = t.error_message or ""
        pattern = (raw.splitlines()[0] if raw else "Неизвестная ошибка")[:120]
        key = (pattern, t.task_type)
        if key not in groups:
            groups[key] = {
                "pattern": pattern,
                "task_type": t.task_type,
                "count": 0,
                "last_failed_at": t.created_at.isoformat(),
                "tasks": [],
            }
        groups[key]["count"] += 1
        groups[key]["tasks"].append(
            FailedTask(
                id=str(t.id),
                task_type=t.task_type,
                error_message=t.error_message,
                created_at=t.created_at.isoformat(),
                error_pattern=pattern,
            )
        )

    error_groups = [
        FailedTaskGroup(**g)
        for g in sorted(groups.values(), key=lambda x: x["last_failed_at"], reverse=True)
    ]

    # 4. Quality funnel — last 30 days
    thirty_days_ago = now - timedelta(days=30)
    funnel_row = (
        await db.execute(
            select(
                func.count(case((Task.status == "completed", Task.id))).label("completed"),
                func.count(
                    case((Task.estimation_status.in_(["estimated", "optimized"]), Task.id))
                ).label("estimated"),
                func.count(case((Task.manually_edited_at.isnot(None), Task.id))).label("manually_edited"),
            ).where(
                Task.deleted_at.is_(None),
                Task.created_at >= thirty_days_ago,
            )
        )
    ).one()

    estimated_count = funnel_row.estimated
    manually_edited_count = funnel_row.manually_edited
    human_edit_rate = (
        round(manually_edited_count / estimated_count * 100, 1) if estimated_count > 0 else 0.0
    )
    quality_funnel = QualityFunnel(
        completed_count=funnel_row.completed,
        estimated_count=estimated_count,
        manually_edited_count=manually_edited_count,
        human_edit_rate=human_edit_rate,
    )

    # 5. Project cards
    all_projects = (
        await db.execute(select(Project).order_by(Project.created_at.desc()))
    ).scalars().all()

    project_ids = [p.id for p in all_projects]
    project_tasks: list[Task] = []
    if project_ids:
        project_tasks = (
            await db.execute(
                select(Task).where(
                    Task.deleted_at.is_(None),
                    Task.project_id.in_(project_ids),
                )
            )
        ).scalars().all()

    tasks_by_project: dict[str, list[Task]] = defaultdict(list)
    for t in project_tasks:
        tasks_by_project[str(t.project_id)].append(t)

    project_cards: list[ProjectCard] = []
    for p in all_projects:
        ptasks = tasks_by_project.get(str(p.id), [])
        total_cost_val = sum(
            float(t.cost)
            for t in ptasks
            if t.cost is not None and t.estimation_status in ("estimated", "optimized")
        )
        last_task_dt = max((t.created_at for t in ptasks), default=None)
        has_active = any(t.status in ("pending", "processing") for t in ptasks)
        has_errors = any(t.status == "failed" for t in ptasks)

        breakdown = TaskTypeBreakdown(
            list_from_grand=sum(1 for t in ptasks if t.task_type == "LIST_FROM_GRAND"),
            list_from_project=sum(1 for t in ptasks if t.task_type == "LIST_FROM_PROJECT"),
            check_completeness=sum(1 for t in ptasks if t.task_type in CHECK_TYPES),
            estimate_from_list=sum(1 for t in ptasks if t.task_type == "ESTIMATE_FROM_LIST"),
            optimization=sum(1 for t in ptasks if t.task_type == "ESTIMATE_OPTIMIZATION"),
        )
        project_cards.append(
            ProjectCard(
                id=str(p.id),
                name=p.name,
                created_at=p.created_at.isoformat(),
                total_cost=total_cost_val if total_cost_val else None,
                last_task_at=last_task_dt.isoformat() if last_task_dt else None,
                task_breakdown=breakdown,
                has_active=has_active,
                has_errors=has_errors,
            )
        )

    # Sort: projects with active tasks or errors first, then newest first within each group
    project_cards.sort(key=lambda x: x.created_at, reverse=True)
    project_cards.sort(key=lambda x: 0 if (x.has_active or x.has_errors) else 1)

    # 6. Orphan tasks count
    orphan_count = (
        await db.execute(
            select(func.count(Task.id)).where(
                Task.deleted_at.is_(None),
                Task.project_id.is_(None),
            )
        )
    ).scalar_one()

    # 7. Task chart — last 10 days by day and task_type
    ten_days_ago = now - timedelta(days=10)
    chart_rows = (
        await db.execute(
            select(
                # type_=DateTime — не для PostgreSQL (там тип и так timestamp), а
                # чтобы результат приходил датой на любом диалекте: ниже вызывается
                # .strftime(), и без объявленного типа SQLite отдал бы строку.
                func.date_trunc(text("'day'"), Task.created_at, type_=DateTime).label("day"),
                Task.task_type,
                func.count(Task.id).label("count"),
            )
            .where(
                Task.deleted_at.is_(None),
                Task.created_at >= ten_days_ago,
            )
            .group_by(func.date_trunc(text("'day'"), Task.created_at), Task.task_type)
            .order_by(func.date_trunc(text("'day'"), Task.created_at))
        )
    ).all()

    chart_data: dict[str, dict] = {}
    for row in chart_rows:
        day_str = row.day.strftime("%Y-%m-%d")
        if day_str not in chart_data:
            chart_data[day_str] = {
                "date": day_str,
                "LIST_FROM_GRAND": 0,
                "LIST_FROM_PROJECT": 0,
                "CHECK_COMPLETENESS": 0,
                "ESTIMATE_FROM_LIST": 0,
                "ESTIMATE_OPTIMIZATION": 0,
            }
        tt = row.task_type
        if tt == "LIST_FROM_GRAND":
            chart_data[day_str]["LIST_FROM_GRAND"] += row.count
        elif tt == "LIST_FROM_PROJECT":
            chart_data[day_str]["LIST_FROM_PROJECT"] += row.count
        elif tt in CHECK_TYPES:
            chart_data[day_str]["CHECK_COMPLETENESS"] += row.count
        elif tt == "ESTIMATE_FROM_LIST":
            chart_data[day_str]["ESTIMATE_FROM_LIST"] += row.count
        elif tt == "ESTIMATE_OPTIMIZATION":
            chart_data[day_str]["ESTIMATE_OPTIMIZATION"] += row.count

    task_chart = [ChartDay(**v) for v in sorted(chart_data.values(), key=lambda x: x["date"])]

    # 8. Price lists status
    price_lists_db = (
        await db.execute(select(PriceList).order_by(PriceList.type))
    ).scalars().all()

    works_count = (
        await db.execute(select(func.count()).select_from(PriceWork))
    ).scalar_one()

    mats_count = (
        await db.execute(select(func.count()).select_from(PriceMaterial))
    ).scalar_one()

    counts_map = {"works": works_count, "materials": mats_count}
    price_list_infos: list[PriceListInfo] = []
    seen_types: set[str] = set()

    for pl in price_lists_db:
        seen_types.add(pl.type)
        price_list_infos.append(
            PriceListInfo(
                type=pl.type,
                updated_at=pl.updated_at.isoformat() if pl.updated_at else None,
                embedding_status=getattr(pl, "embedding_status", None),
                items_count=counts_map.get(pl.type, 0),
            )
        )

    for pl_type in ("works", "materials"):
        if pl_type not in seen_types:
            price_list_infos.append(
                PriceListInfo(
                    type=pl_type,
                    updated_at=None,
                    embedding_status=None,
                    items_count=counts_map.get(pl_type, 0),
                )
            )

    # 9. API costs from api_call_log
    week_ago = now - timedelta(days=7)

    cost_rows = (
        await db.execute(
            select(
                func.sum(ApiCallLog.cost_usd).label("total_cost"),
                func.sum(ApiCallLog.input_tokens).label("total_input"),
                func.sum(ApiCallLog.cache_read_tokens).label("total_cache_read"),
                func.count(ApiCallLog.id).label("calls"),
            ).where(ApiCallLog.called_at >= thirty_days_ago)
        )
    ).one()

    today_cost_row = (
        await db.execute(
            select(func.sum(ApiCallLog.cost_usd)).where(ApiCallLog.called_at >= today_start)
        )
    ).scalar_one()

    week_cost_row = (
        await db.execute(
            select(func.sum(ApiCallLog.cost_usd)).where(ApiCallLog.called_at >= week_ago)
        )
    ).scalar_one()

    # Cache hit rate: cache_read_tokens / (input_tokens + cache_read_tokens)
    total_input = cost_rows.total_input or 0
    total_cache_read = cost_rows.total_cache_read or 0
    denom = total_input + total_cache_read
    cache_hit_rate = round(total_cache_read / denom * 100, 1) if denom > 0 else 0.0

    # Breakdown by task_type (join with tasks table)
    breakdown_rows = (
        await db.execute(
            select(
                Task.task_type,
                func.sum(ApiCallLog.cost_usd).label("cost_usd"),
                func.count(ApiCallLog.id).label("calls_count"),
            )
            .outerjoin(Task, ApiCallLog.task_id == Task.id)
            .where(ApiCallLog.called_at >= thirty_days_ago)
            .group_by(Task.task_type)
        )
    ).all()

    by_task_type = [
        ApiCostByTaskType(
            task_type=row.task_type,
            cost_usd=round(float(row.cost_usd or 0), 4),
            calls_count=row.calls_count,
        )
        for row in sorted(breakdown_rows, key=lambda r: float(r.cost_usd or 0), reverse=True)
    ]

    api_costs = ApiCosts(
        today_usd=round(float(today_cost_row or 0), 4),
        week_usd=round(float(week_cost_row or 0), 4),
        month_usd=round(float(cost_rows.total_cost or 0), 4),
        cache_hit_rate=cache_hit_rate,
        by_task_type=by_task_type,
    )

    return DashboardStats(
        pulse=pulse,
        active_queue=active_queue,
        errors=error_groups,
        quality_funnel=quality_funnel,
        projects=project_cards,
        orphan_tasks_count=orphan_count,
        task_chart=task_chart,
        price_lists=price_list_infos,
        api_costs=api_costs,
    )

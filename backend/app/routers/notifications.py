"""Системные уведомления для фронта — курсорная лента событий.

Единственный сегодняшний вид события — «баланс API пополнен, задачи возобновлены»
(пишет resume_poller в worker-процессе). Фронт хранит id последнего показанного
события в localStorage и спрашивает «что нового после N», поэтому эндпоинт не
хранит состояние прочтения на сервере: пользователей единицы, а событие такого
рода случается раз в недели.

RBAC: событие глобальное, но список возобновлённых задач — нет. Менеджер видит
все, ПМ — только свои и общие; если ПМ не видно ни одной задачи из события, само
событие ему не показывается (иначе это уведомление о чужой работе).

План: plans/2026-07-28-balance-restored-notification.md, Фаза 3.
"""
from datetime import datetime
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.system_event import SystemEvent
from app.models.task import Task
from app.utils.auth import get_current_user
from app.utils.permissions import is_manager, visibility_filter

logger = structlog.get_logger()

router = APIRouter(prefix="/notifications", tags=["notifications"])

MAX_LIMIT = 50


class NotificationTask(BaseModel):
    id: str
    name: Optional[str] = None


class SystemNotification(BaseModel):
    id: int
    kind: str
    created_at: datetime
    resumed_count: int
    tasks: list[NotificationTask]


class SystemNotificationsResponse(BaseModel):
    """`cursor` — id последнего ПРОСМОТРЕННОГО сервером события, а не последнего
    показанного. Возвращается отдельно от списка: событие может быть отфильтровано
    по правам, и без явного курсора фронт запрашивал бы его снова и снова."""

    cursor: int
    events: list[SystemNotification]


@router.get("/system", response_model=SystemNotificationsResponse)
async def list_system_notifications(
    since_id: int = Query(0, ge=0, description="id последнего показанного события"),
    limit: int = Query(20, ge=1, le=MAX_LIMIT),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """События новее курсора, по возрастанию id."""
    events = (
        (
            await db.execute(
                select(SystemEvent)
                .where(SystemEvent.id > since_id)
                .order_by(SystemEvent.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not events:
        return SystemNotificationsResponse(cursor=since_id, events=[])

    cursor = max(e.id for e in events)

    # Одним запросом на все события: id задач из payload → видимые пользователю.
    all_ids: list[str] = []
    for event in events:
        all_ids.extend((event.payload or {}).get("resumed_task_ids") or [])
    if not all_ids:
        return SystemNotificationsResponse(cursor=cursor, events=[])

    stmt = select(Task.id, Task.name).where(Task.id.in_(set(all_ids)))
    vis = visibility_filter(Task, current_user)
    if vis is not None:
        stmt = stmt.where(vis)
    visible = {row.id: row.name for row in (await db.execute(stmt)).all()}

    manager = is_manager(current_user.get("role"))
    out: list[SystemNotification] = []
    for event in events:
        ids = (event.payload or {}).get("resumed_task_ids") or []
        tasks = [NotificationTask(id=tid, name=visible[tid]) for tid in ids if tid in visible]
        # Задача могла быть удалена — тогда событие остаётся, но без карточек.
        # Менеджеру такое всё равно показываем (он отвечает за баланс), ПМ — нет.
        if not tasks and not manager:
            continue
        out.append(
            SystemNotification(
                id=event.id,
                kind=event.kind,
                created_at=event.created_at,
                resumed_count=len(ids) if manager else len(tasks),
                tasks=tasks,
            )
        )
    return SystemNotificationsResponse(cursor=cursor, events=out)

"""
Периодический поллер авто-возобновления задач на паузе (paused).

При исчерпании баланса Anthropic задача уходит в статус `paused` с сохранённым
чекпоинтом (см. Фаза 3). У Anthropic НЕТ API проверки баланса — узнать про
пополнение можно только пробным вызовом. Поэтому раз в N минут поллер берёт
paused-задачи с чекпоинтом, атомарно помечает их `pending` и запускает обработку
заново с точки прерывания. Если баланс всё ещё пуст — задача быстро упадёт на
первом же вызове Claude и снова уйдёт в `paused` (тихо, self-healing).

Гард от двойного запуска: захват делается атомарным UPDATE со `WHERE status =
'paused'` — уже захваченная (переведённая в pending) задача повторно не берётся.
Плюс scheduler регистрирует job с max_instances=1.

Логика вынесена из main.py, чтобы не тянуть apscheduler в тесты (как batch_poller).
План: plans/2026-07-21-resume-and-balance-pause.md, Фаза 4.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models.task import Task
from app.services.checkpoint import has_resumable_checkpoint

logger = structlog.get_logger()

# Ссылки на fire-and-forget задачи, чтобы их не собрал GC до завершения.
_background_runs: set = set()

# Единый предикат возобновляемости — тот же, что в ручном resume-эндпоинте
# (app/routers/tasks.py: resume_task). Алиас сохранён для обратной совместимости.
_has_checkpoint = has_resumable_checkpoint


async def _find_resumable_paused_ids(db) -> list[str]:
    """ID задач в статусе paused, у которых есть чекпоинт (Python-фильтр — DB-agnostic)."""
    result = await db.execute(select(Task).where(Task.status == "paused"))
    return [t.id for t in result.scalars().all() if _has_checkpoint(t.progress_data)]


async def _claim(db, task_id: str) -> bool:
    """Атомарно перевести задачу paused→pending. Возвращает True, если захвачена
    именно этим вызовом (не была уже перехвачена/изменена)."""
    res = await db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == "paused")
        .values(
            status="pending",
            error_message=None,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return res.rowcount == 1


async def resume_paused_tasks(session_factory=AsyncSessionLocal, runner=None) -> list[str]:
    """Один проход: захватить paused-задачи с чекпоинтом и запустить их заново.

    Возвращает список ID реально захваченных (paused→pending) задач.
    `runner` (по умолчанию — фоновый запуск обработки) инъектируется для тестов.
    """
    if runner is None:
        # Ленивый импорт: избегаем цикла (tasks.py тянет много зависимостей) и
        # держим импорт main.py лёгким.
        from app.routers.tasks import _run_task_in_background
        runner = _run_task_in_background

    async with session_factory() as db:
        candidates = await _find_resumable_paused_ids(db)

    if not candidates:
        return []

    claimed: list[str] = []
    for task_id in candidates:
        async with session_factory() as db:
            if await _claim(db, task_id):
                claimed.append(task_id)

    if not claimed:
        return []

    logger.info("Auto-resuming paused tasks", count=len(claimed))
    for task_id in claimed:
        run = asyncio.create_task(runner(task_id))
        _background_runs.add(run)
        run.add_done_callback(_background_runs.discard)

    return claimed

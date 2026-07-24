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


async def _claim_and_enqueue(db, task_id: str) -> bool:
    """Прод-путь авто-резюме: АТОМАРНО (одна транзакция) paused→pending + постановка
    durable-job `task.process`. Так задача не осиротеет в `pending` без Job, если
    воркер рестартует сразу после захвата (P1: раньше запускался прямой
    _run_task_in_background мимо очереди — reclaim его не подхватывал)."""
    from app.models.job import Job

    res = await db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == "paused")
        .values(status="pending", error_message=None, updated_at=datetime.now(timezone.utc))
    )
    if res.rowcount != 1:
        await db.rollback()
        return False
    task = await db.get(Task, task_id)
    db.add(
        Job(
            kind="task.process",
            payload={"task_id": task_id},
            owner_id=(task.owner_id if task else None),
            status="queued",
        )
    )
    await db.commit()
    return True


async def resume_paused_tasks(session_factory=AsyncSessionLocal, runner=None) -> list[str]:
    """Один проход: захватить paused-задачи с чекпоинтом и переочередить их.

    Возвращает список ID реально захваченных (paused→pending) задач.

    Прод (`runner is None`): захват и постановка durable-job атомарны
    (`_claim_and_enqueue`) — обработку доведёт worker из очереди, в рамках лимита
    WORKER_CONCURRENCY и с reclaim-подстраховкой.
    Тесты могут инъектировать `runner` — тогда используется старый путь
    (`_claim` + прямой вызов runner) для проверки оркестрации.
    """
    async with session_factory() as db:
        candidates = await _find_resumable_paused_ids(db)

    if not candidates:
        return []

    claimed: list[str] = []
    for task_id in candidates:
        async with session_factory() as db:
            ok = await (_claim(db, task_id) if runner is not None else _claim_and_enqueue(db, task_id))
            if ok:
                claimed.append(task_id)

    if not claimed:
        return []

    logger.info("Auto-resuming paused tasks", count=len(claimed))
    # Прод-путь уже поставил job в очередь внутри _claim_and_enqueue. Прямой запуск —
    # только для инъектированного тестового runner.
    if runner is not None:
        for task_id in claimed:
            run = asyncio.create_task(runner(task_id))
            _background_runs.add(run)
            run.add_done_callback(_background_runs.discard)

    return claimed

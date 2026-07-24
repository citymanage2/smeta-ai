"""Отдельный worker-процесс: исполняет job из durable-очереди.

Запуск: python -m app.worker

- Пул из WORKER_CONCURRENCY async-слотов (реальный параллелизм задач).
- claim → handler(kind) → complete/fail; heartbeat продлевает визибилити.
- Планировщик (max_instances=1): reclaim зависших job + batch/resume поллеры.
- Graceful shutdown по SIGTERM/SIGINT: перестаём брать новые job, даём текущим доиграть.

Вся CPU-работа обработки уходит из web-процесса — web остаётся отзывчивым.
"""
import asyncio
import os
import signal
import socket
from typing import Awaitable, Callable

import structlog
from sqlalchemy import update

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.job import Job
from app.services import job_queue

logger = structlog.get_logger()

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"

# Событие остановки: poll-loop перестаёт брать новые job.
_shutdown = asyncio.Event()


# ---------------------------------------------------------------------------
# Реестр обработчиков: kind → async handler(payload, db)
# ---------------------------------------------------------------------------

async def _handle_task_process(payload: dict, db) -> None:
    """Основной пайплайн: 6 типов задач через TaskProcessor."""
    from app.services.task_processor import process_task
    task_id = payload.get("task_id")
    if not task_id:
        raise ValueError("task.process: payload без task_id")
    await process_task(task_id, db)


HANDLERS: dict[str, Callable[[dict, object], Awaitable[None]]] = {
    "task.process": _handle_task_process,
}


# ---------------------------------------------------------------------------
# Исполнение одной job
# ---------------------------------------------------------------------------

async def _heartbeat_loop(job_id: int, interval: float) -> None:
    """Периодически продлевает claimed_at, пока job исполняется."""
    try:
        while True:
            await asyncio.sleep(interval)
            async with AsyncSessionLocal() as db:
                await job_queue.heartbeat(db, job_id)
    except asyncio.CancelledError:
        pass


async def run_job(job: Job) -> None:
    """Выполнить одну захваченную job: handler → complete, либо requeue/fail."""
    hb_interval = max(30.0, settings.JOB_VISIBILITY_TIMEOUT_S / 3)
    hb = asyncio.create_task(_heartbeat_loop(job.id, hb_interval))
    try:
        handler = HANDLERS.get(job.kind)
        if handler is None:
            raise ValueError(f"Неизвестный kind job: {job.kind}")
        async with AsyncSessionLocal() as db:
            await handler(job.payload, db)
        async with AsyncSessionLocal() as db:
            await job_queue.complete(db, job.id)
        logger.info("Job done", job_id=job.id, kind=job.kind)
    except Exception as e:  # noqa: BLE001 — любая ошибка обработчика
        logger.error("Job failed", job_id=job.id, kind=job.kind, error=str(e))
        async with AsyncSessionLocal() as db:
            if job.attempts >= settings.JOB_MAX_ATTEMPTS:
                await job_queue.fail(db, job.id, str(e))
            else:
                # Вернуть в очередь для повторной попытки (attempts уже увеличен при claim).
                await db.execute(
                    update(Job)
                    .where(Job.id == job.id)
                    .values(status="queued", claimed_by=None, claimed_at=None, last_error=str(e)[:1000])
                )
                await db.commit()
    finally:
        hb.cancel()
        await asyncio.gather(hb, return_exceptions=True)


# ---------------------------------------------------------------------------
# Poll-loop
# ---------------------------------------------------------------------------

async def _poll_loop(sem: asyncio.Semaphore, inflight: set) -> None:
    while not _shutdown.is_set():
        await sem.acquire()
        if _shutdown.is_set():
            sem.release()
            break
        async with AsyncSessionLocal() as db:
            job = await job_queue.claim_one(db, WORKER_ID)
        if job is None:
            sem.release()
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=settings.JOB_POLL_INTERVAL_S)
            except asyncio.TimeoutError:
                pass
            continue

        async def _run_and_release(j: Job) -> None:
            try:
                await run_job(j)
            finally:
                sem.release()

        task = asyncio.create_task(_run_and_release(job))
        inflight.add(task)
        task.add_done_callback(inflight.discard)


# ---------------------------------------------------------------------------
# Планировщик обслуживания (reclaim + поллеры)
# ---------------------------------------------------------------------------

async def _reclaim_job() -> None:
    async with AsyncSessionLocal() as db:
        n = await job_queue.reclaim_stale(
            db, settings.JOB_VISIBILITY_TIMEOUT_S, settings.JOB_MAX_ATTEMPTS
        )
    if n:
        logger.info("Reclaimed stale jobs", count=n)


async def _cleanup_price_cache() -> None:
    """Удалить протухшие записи кэша цен (>30 дней) и перезагрузить in-memory кэш.
    Перенесено из web-lifespan."""
    from sqlalchemy import text
    from app.services import price_service

    async with AsyncSessionLocal() as db:
        rw = await db.execute(
            text("DELETE FROM price_cache_works WHERE updated_at < now() - interval '30 days' RETURNING id")
        )
        rm = await db.execute(
            text("DELETE FROM price_cache_materials WHERE updated_at < now() - interval '30 days' RETURNING id")
        )
        deleted_works, deleted_materials = len(rw.fetchall()), len(rm.fetchall())
        await db.commit()
    logger.info("Price cache cleanup done", works=deleted_works, materials=deleted_materials)
    async with AsyncSessionLocal() as db:
        await price_service.load_cache(db)


def _build_scheduler():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from app.services.batch_poller import poll_batch_tasks
    from app.services.resume_poller import resume_paused_tasks

    scheduler = AsyncIOScheduler()
    scheduler.add_job(_reclaim_job, "interval", seconds=60, max_instances=1)
    scheduler.add_job(poll_batch_tasks, "interval", seconds=60, max_instances=1)
    scheduler.add_job(resume_paused_tasks, "interval", minutes=10, max_instances=1)
    scheduler.add_job(_cleanup_price_cache, "interval", hours=24, max_instances=1)
    return scheduler


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def main() -> None:
    logger.info("Worker starting", worker_id=WORKER_ID, concurrency=settings.WORKER_CONCURRENCY)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _shutdown.set)
        except NotImplementedError:
            pass  # Windows

    sem = asyncio.Semaphore(settings.WORKER_CONCURRENCY)
    inflight: set = set()

    scheduler = _build_scheduler()
    scheduler.start()

    try:
        await _poll_loop(sem, inflight)
    finally:
        logger.info("Worker shutting down — draining in-flight jobs", count=len(inflight))
        scheduler.shutdown(wait=False)
        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)
        logger.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())

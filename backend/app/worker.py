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

# id job, которые прямо сейчас исполняются этим процессом. Нужен на остановке:
# недоигранные возвращаем в очередь, не списывая попытку (плановый рестарт —
# не сбой обработки). См. plans/2026-07-29-osirotevshie-zadachi-v-obrabotke.md.
_inflight_job_ids: set[int] = set()


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


async def _handle_task_optimize(payload: dict, db) -> None:
    """Оптимизация сметы. estimate_bytes до-читаем из БД (не был в payload)."""
    from sqlalchemy import select
    from app.routers.tasks import _run_optimization_background
    from app.models.result import TaskResult
    from app.services import storage_service
    task_id = payload["task_id"]
    tr = (
        await db.execute(
            select(TaskResult).where(TaskResult.task_id == task_id, TaskResult.slot == "estimate")
        )
    ).scalar_one_or_none()
    estimate_bytes = await storage_service.load_bytes(tr.storage_key) if tr else None
    await _run_optimization_background(
        task_id, payload.get("items", []), payload.get("prompt"), estimate_bytes, AsyncSessionLocal
    )


async def _handle_task_fix_prices(payload: dict, db) -> None:
    from app.services.task_processor import fix_empty_prices_background
    await fix_empty_prices_background(payload["task_id"], AsyncSessionLocal)


async def _handle_version_optimize(payload: dict, db) -> None:
    from app.routers.estimate_versions import _run_optimization_step
    await _run_optimization_step(payload["task_id"], payload["step"])


async def _handle_version_fill_prices(payload: dict, db) -> None:
    from app.routers.estimate_versions import _run_fill_prices_step
    await _run_fill_prices_step(payload["task_id"])


async def _handle_retrain(payload: dict, db) -> None:
    from app.services import retraining_service
    await retraining_service.run_training_job(payload["job_id"], db)


HANDLERS: dict[str, Callable[[dict, object], Awaitable[None]]] = {
    "task.process": _handle_task_process,
    "task.optimize": _handle_task_optimize,
    "task.fix_prices": _handle_task_fix_prices,
    "version.optimize": _handle_version_optimize,
    "version.fill_prices": _handle_version_fill_prices,
    "retrain": _handle_retrain,
}


# ---------------------------------------------------------------------------
# Исполнение одной job
# ---------------------------------------------------------------------------

async def _heartbeat_loop(job_id: int, interval: float) -> None:
    """Периодически продлевает claimed_at, пока job исполняется.

    Транзиентный сбой БД (обрыв соединения, таймаут пула) НЕ убивает цикл:
    логируем и продолжаем. Иначе один сбой оставил бы длинную живую job без
    heartbeat → она протухла бы и её ошибочно реклеймили в параллельный прогон
    (P0-B). Останавливается только по CancelledError (job завершилась).
    """
    while True:
        try:
            await asyncio.sleep(interval)
            async with AsyncSessionLocal() as db:
                await job_queue.heartbeat(db, job_id)
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001 — транзиентный сбой: логируем и продолжаем
            logger.warning("Heartbeat failed, will retry", job_id=job_id, error=str(e))


async def run_job(job: Job) -> None:
    """Выполнить одну захваченную job: handler → complete, либо requeue/fail."""
    # Раз в минуту, а не раз в visibility/3 (=300 с): claimed_at теперь ещё и
    # признак жизни в карточке задачи, и с пятиминутным шагом индикатор большую
    # часть времени показывал бы «сигнала нет N минут» у здоровой задачи.
    # Для reclaim'а частый heartbeat только надёжнее — он смотрит на порог 900 с.
    hb_interval = min(60.0, max(5.0, settings.JOB_VISIBILITY_TIMEOUT_S / 3))
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
        try:
            async with AsyncSessionLocal() as db:
                job = await job_queue.claim_one(db, WORKER_ID)
        except Exception as e:  # noqa: BLE001 — БД недоступна/таблицы ещё нет (первый деплой)
            logger.warning("Claim failed, retrying", error=str(e))
            sem.release()
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=settings.JOB_POLL_INTERVAL_S)
            except asyncio.TimeoutError:
                pass
            continue
        if job is None:
            sem.release()
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=settings.JOB_POLL_INTERVAL_S)
            except asyncio.TimeoutError:
                pass
            continue

        async def _run_and_release(j: Job) -> None:
            _inflight_job_ids.add(j.id)
            try:
                await run_job(j)
            finally:
                _inflight_job_ids.discard(j.id)
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


async def _sweep_orphans_job() -> None:
    """Второй эшелон: задачи «в работе», за которыми не стоит ни одна живая job.

    reclaim возвращает job в очередь, но если job ушла в терминальный failed или
    её запись потеряна — задача осталась бы в «Обработке» навсегда.
    """
    async with AsyncSessionLocal() as db:
        n = await job_queue.sweep_orphaned_tasks(db, settings.TASK_ORPHAN_GRACE_S)
    if n:
        logger.warning("Orphaned tasks marked failed", count=n)


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
    scheduler.add_job(_sweep_orphans_job, "interval", minutes=5, max_instances=1)
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
            # Ограниченный дренаж: ждём завершения текущих job не дольше
            # JOB_DRAIN_TIMEOUT_S (меньше SIGKILL-грейса Timeweb).
            try:
                await asyncio.wait_for(
                    asyncio.gather(*list(inflight), return_exceptions=True),
                    timeout=settings.JOB_DRAIN_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                await _abort_undrained(inflight)
        logger.info("Worker stopped")


async def _abort_undrained(inflight: set) -> None:
    """Не успели доиграть за дренаж — вернуть job в очередь, не списав попытку.

    Порядок важен: сначала ОТМЕНЯЕМ обработчики, только потом возвращаем job в
    очередь. Иначе при деплое (старый и новый контейнеры сосуществуют) новый
    worker забрал бы job, которую этот процесс ещё считает, — двойной прогон и
    двойная стоимость API.

    `CancelledError` — BaseException, поэтому `except Exception` в TaskProcessor
    её не проглотит и ложного `failed` у задачи не будет: она вернётся в работу
    вместе с job. Снимок id берём ДО отмены — `_run_and_release` чистит множество
    в своём finally.
    """
    stuck_ids = list(_inflight_job_ids)
    pending = [t for t in inflight if not t.done()]
    logger.warning("Drain timeout — отменяем обработчики", remaining=len(pending))

    for t in pending:
        t.cancel()
    try:
        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=3.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        logger.warning("Не дождались отмены обработчиков", remaining=len(stuck_ids))

    try:
        async with AsyncSessionLocal() as db:
            await job_queue.requeue_after_shutdown(db, stuck_ids, WORKER_ID)
    except Exception as e:  # noqa: BLE001 — БД может быть уже недоступна; job вернёт reclaim
        logger.warning("Requeue on shutdown failed, will rely on reclaim", error=str(e))


if __name__ == "__main__":
    asyncio.run(main())

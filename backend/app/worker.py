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
import sys
from typing import Awaitable, Callable, Optional

import structlog
from sqlalchemy import update

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.job import Job
from app.services import job_queue

# Логирование настраиваем и здесь: `structlog.configure` вызывался только в
# main.py (web), поэтому строки обработчика шли в дефолтном формате — без ISO-времени
# и в другом виде, чем строки web. В общем логе приложения (Timeweb показывает оба
# контейнера вперемешку) это мешало сопоставлять события по времени.
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)

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
    """Основной пайплайн: 6 типов задач через TaskProcessor.

    `_job_id` подкладывает `run_job` — по нему прогон отличает «меня сменили
    перезапуском» от «всё в порядке» и не считает параллельно новому прогону.
    """
    from app.services.task_processor import process_task
    task_id = payload.get("task_id")
    if not task_id:
        raise ValueError("task.process: payload без task_id")
    await process_task(task_id, db, job_id=payload.get("_job_id"))


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

def rss_mb() -> Optional[float]:
    """Память процесса, МБ. None — платформа не дала цифру.

    Без внешних зависимостей (psutil в проекте нет): на Linux, где живёт прод, —
    честный текущий RSS из /proc/self/status; иначе — пиковый ru_maxrss из
    resource (macOS отдаёт байты, Linux — килобайты).
    """
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        pass
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        return round(peak / divisor, 1)
    except Exception:  # noqa: BLE001 — измерение не обязано работать везде
        return None


def _rss_fields(rss_before: Optional[float]) -> dict:
    """Поля памяти для лога job: сколько сейчас и сколько прибавилось за задачу."""
    rss_after = rss_mb()
    if rss_after is None:
        return {}
    fields = {"rss_mb": rss_after}
    if rss_before is not None:
        fields["rss_delta_mb"] = round(rss_after - rss_before, 1)
    return fields


async def _report_memory_if_high(rss: Optional[float]) -> None:
    """Записать жалобу на память, чтобы её было видно в админке.

    Раньше расход памяти не измерялся вообще, и вопрос «сколько задач считать
    параллельно» решался наугад. Web память воркера измерить не может (другой
    контейнер), поэтому единственный канал — строка в БД, её читает
    `/admin/queue-health`. Пишем только при превышении порога и не чаще раза в
    30 минут: диагностика не должна сама создавать нагрузку.
    """
    threshold = settings.WORKER_RSS_WARN_MB
    if rss is None or threshold <= 0 or rss < threshold:
        return

    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models.system_event import KIND_WORKER_MEMORY_HIGH, SystemEvent

    logger.warning(
        "Worker memory high", rss_mb=rss, threshold_mb=threshold,
        concurrency=settings.WORKER_CONCURRENCY,
    )
    try:
        async with AsyncSessionLocal() as db:
            last_at = (
                await db.execute(
                    select(SystemEvent.created_at)
                    .where(SystemEvent.kind == KIND_WORKER_MEMORY_HIGH)
                    .order_by(SystemEvent.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last_at is not None:
                if last_at.tzinfo is None:  # SQLite отдаёт naive
                    last_at = last_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - last_at < timedelta(minutes=30):
                    return
            db.add(
                SystemEvent(
                    kind=KIND_WORKER_MEMORY_HIGH,
                    payload={
                        "rss_mb": rss,
                        "threshold_mb": threshold,
                        "concurrency": settings.WORKER_CONCURRENCY,
                    },
                )
            )
            await db.commit()
    except Exception as e:  # noqa: BLE001 — жалоба на память не важнее самой работы
        logger.warning("Worker memory event not recorded", error=str(e))


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
    # Память до/после job: сколько стоит одна задача — единственный способ
    # осознанно выбрать WORKER_CONCURRENCY вместо угадывания.
    rss_before = rss_mb()
    logger.info("Job starting", job_id=job.id, kind=job.kind, rss_mb=rss_before)
    try:
        handler = HANDLERS.get(job.kind)
        if handler is None:
            raise ValueError(f"Неизвестный kind job: {job.kind}")
        # `_job_id` в копии payload (саму запись не меняем): обработчику нужно
        # знать, под какой job он идёт, чтобы остановиться, если его сменили.
        async with AsyncSessionLocal() as db:
            await handler({**(job.payload or {}), "_job_id": job.id}, db)
        async with AsyncSessionLocal() as db:
            await job_queue.complete(db, job.id)
        logger.info(
            "Job done", job_id=job.id, kind=job.kind, **_rss_fields(rss_before)
        )
    except Exception as e:  # noqa: BLE001 — любая ошибка обработчика
        logger.error(
            "Job failed", job_id=job.id, kind=job.kind, error=str(e),
            **_rss_fields(rss_before),
        )
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
        await _report_memory_if_high(rss_mb())


# ---------------------------------------------------------------------------
# Poll-loop
# ---------------------------------------------------------------------------

def _memory_brake_engaged() -> bool:
    """Не брать НОВУЮ задачу, пока память выше порога и хоть одна уже считается.

    Жёсткое число слотов не знает, что взяло: четыре тяжёлые сметы валят процесс,
    четыре лёгких — нет. Тормоз делает параллельность адаптивной: под нагрузкой
    задачи идут по одной, в спокойное время занимаются все слоты. Задачи не
    теряются — ждут в очереди.

    Пустой процесс не тормозим никогда: иначе высокая база (загруженный прайс,
    матрицы эмбеддингов) заперла бы очередь навсегда — брать было бы нечего, а
    память сама не упадёт.
    """
    limit = settings.WORKER_RSS_PAUSE_MB
    if limit <= 0 or not _inflight_job_ids:
        return False
    rss = rss_mb()
    if rss is None or rss < limit:
        return False
    logger.info(
        "Memory brake — новую задачу не берём",
        rss_mb=rss,
        limit_mb=limit,
        running=len(_inflight_job_ids),
    )
    return True


async def _poll_loop(sem: asyncio.Semaphore, inflight: set) -> None:
    while not _shutdown.is_set():
        await sem.acquire()
        if _shutdown.is_set():
            sem.release()
            break
        if _memory_brake_engaged():
            sem.release()
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=settings.JOB_POLL_INTERVAL_S)
            except asyncio.TimeoutError:
                pass
            continue
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


async def _warm_price_cache() -> None:
    """Загрузить корпоративный прайс в память ДО того, как будет взята первая job.

    Без этого шага обработчик считал сметы с ПУСТЫМ прайсом: поиск цены выходит
    по `_works_embeddings is None` и мгновенно отвечает «не найдено» на все
    позиции, а дальше каждая уходит в ИИ с платным web-поиском — часы обработки,
    лишние деньги и цены не из корпоративного прайса. В web кэш грелся в lifespan
    (main.py), а в worker `load_cache` вызывался ТОЛЬКО внутри суточной чистки
    (`_cleanup_price_cache`), то есть впервые через 24 часа после старта — а
    процесс перезапускается на каждом деплое, так что до чистки дело не доходило.

    Ошибка не смертельна: на первом деплое БД может быть ещё не готова (web
    только applies миграции). Poll-loop поднимется и без прайса, а прогрев
    дожмёт `_ensure_price_cache`.
    """
    from app.services import price_service

    try:
        async with AsyncSessionLocal() as db:
            await price_service.load_cache(db)
        logger.info("Price cache warmed")
    except Exception as e:  # noqa: BLE001 — БД может быть недоступна на первом деплое
        logger.warning("Price cache warmup failed — до прогрева сметы пойдут без прайса", error=str(e))


async def _ensure_price_cache() -> None:
    """Дожать прогрев, если при старте БД была недоступна.

    Уже загруженный кэш не перезагружаем: полная перезагрузка — это 4 SELECT без
    лимита плюс пересборка numpy-матриц, и гонять её по расписанию мы намеренно
    перестали (коммит 04458b7). Здесь только добор пропущенного прогрева.
    """
    from app.services import price_service

    if price_service.is_cache_loaded():
        return
    await _warm_price_cache()


def _build_scheduler():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from app.services.batch_poller import poll_batch_tasks
    from app.services.resume_poller import resume_paused_tasks

    scheduler = AsyncIOScheduler()
    scheduler.add_job(_reclaim_job, "interval", seconds=60, max_instances=1)
    scheduler.add_job(_sweep_orphans_job, "interval", minutes=5, max_instances=1)
    scheduler.add_job(poll_batch_tasks, "interval", seconds=60, max_instances=1)
    scheduler.add_job(resume_paused_tasks, "interval", minutes=10, max_instances=1)
    scheduler.add_job(_ensure_price_cache, "interval", minutes=5, max_instances=1)
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

    # ДО poll-loop: первая же job должна видеть прайс, иначе смета считается без
    # корпоративных цен и уходит целиком в ИИ.
    await _warm_price_cache()

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

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
from typing import Awaitable, Callable, Optional

import structlog
from sqlalchemy import update

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.job import Job
from app.services import job_queue
from app.utils.memory import rss_mb, snapshot as memory_snapshot

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

# Когда (монотонные секунды) начались исполняемые сейчас job — для разноса
# захватов: память задачи проявляется не мгновенно, и решать «взять ли ещё одну»
# по занятости в первые секунды бессмысленно.
_inflight_started_at: dict[int, float] = {}

# job_id → task_id исполняемых сейчас задач. Нужен, чтобы этот процесс не начал
# считать одну и ту же задачу дважды: под нагрузкой heartbeat опаздывает, реклейм
# принимает живой прогон за мёртвый и выдаёт второй — нагрузка растёт, опоздание
# усиливается, появляется третий. Петлю видно в логе задачи как повторяющееся
# «Начало обработки задачи...» (plans/2026-07-30-parallelnaya-obrabotka-umiraet.md).
_inflight_task_ids: dict[int, str] = {}


def _monotonic() -> float:
    """Монотонные секунды. Отдельной функцией — чтобы подменять в тестах."""
    import time

    return time.monotonic()


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
    await process_task(
        task_id,
        db,
        job_id=payload.get("_job_id"),
        job_attempt=payload.get("_job_attempt"),
    )


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


async def _handle_document_analogs(payload: dict, db) -> None:
    """Поиск аналогов по позициям документа (план 2026-08-02, Фаза 11).

    Задача фоновая, потому что идёт в интернет и занимает минуты. Документ она
    не меняет: результат — предложения, которые человек принимает сам.
    """
    from app.services import analogs_service

    run_id = payload.get("run_id")
    if not run_id:
        raise ValueError("document.analogs: payload без run_id")
    try:
        await analogs_service.process_run(db, run_id)
    except Exception as exc:  # noqa: BLE001 — прогон не должен остаться «идущим»
        # Без этого упавшая задача оставила бы прогон в статусе «идёт», и
        # человек не смог бы запустить поиск заново.
        await analogs_service.mark_failed(db, run_id, str(exc))
        raise


HANDLERS: dict[str, Callable[[dict, object], Awaitable[None]]] = {
    "task.process": _handle_task_process,
    "task.optimize": _handle_task_optimize,
    "task.fix_prices": _handle_task_fix_prices,
    "version.optimize": _handle_version_optimize,
    "version.fill_prices": _handle_version_fill_prices,
    "retrain": _handle_retrain,
    "document.analogs": _handle_document_analogs,
}


# ---------------------------------------------------------------------------
# Исполнение одной job
# ---------------------------------------------------------------------------

def _rss_fields(rss_before: Optional[float]) -> dict:
    """Поля памяти для лога job: сколько сейчас и сколько прибавилось за задачу."""
    rss_after = rss_mb()
    if rss_after is None:
        return {}
    fields = {"rss_mb": rss_after}
    if rss_before is not None:
        fields["rss_delta_mb"] = round(rss_after - rss_before, 1)
    return fields


async def _record_event_throttled(kind: str, payload: dict, min_interval_s: float) -> bool:
    """Записать системное событие, но не чаще раза в `min_interval_s`.

    Общий механизм для всех сигналов обработчика в БД: web — другой контейнер и
    лога воркера не видит, а лог Timeweb пользователю недоступен. Поэтому всё, что
    надо знать при разборе («памяти много», «heartbeat не пишется»), едет строкой в
    `system_events` и читается диагностикой админки. Троттлинг — чтобы диагностика
    не создавала нагрузку сама.

    Возвращает True, если запись сделана. Никогда не бросает: диагностика не важнее
    самой работы.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models.system_event import SystemEvent

    try:
        async with AsyncSessionLocal() as db:
            last_at = (
                await db.execute(
                    select(SystemEvent.created_at)
                    .where(SystemEvent.kind == kind)
                    .order_by(SystemEvent.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last_at is not None:
                if last_at.tzinfo is None:  # SQLite отдаёт naive
                    last_at = last_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - last_at < timedelta(seconds=min_interval_s):
                    return False
            db.add(SystemEvent(kind=kind, payload=payload))
            await db.commit()
            return True
    except Exception as e:  # noqa: BLE001 — диагностика не важнее самой работы
        logger.warning("System event not recorded", kind=kind, error=str(e))
        return False


async def _report_memory_if_high(rss: Optional[float]) -> None:
    """Записать жалобу на память, чтобы её было видно в админке.

    Раньше расход памяти не измерялся вообще, и вопрос «сколько задач считать
    параллельно» решался наугад. Web память воркера измерить не может (другой
    контейнер), поэтому единственный канал — строка в БД, её читает
    `/admin/queue-health`.
    """
    threshold = settings.WORKER_RSS_WARN_MB
    if rss is None or threshold <= 0 or rss < threshold:
        return

    from app.models.system_event import KIND_WORKER_MEMORY_HIGH

    logger.warning(
        "Worker memory high", rss_mb=rss, threshold_mb=threshold,
        concurrency=settings.WORKER_CONCURRENCY,
    )
    await _record_event_throttled(
        KIND_WORKER_MEMORY_HIGH,
        {
            "rss_mb": rss,
            "threshold_mb": threshold,
            "concurrency": settings.WORKER_CONCURRENCY,
            "running": len(_inflight_job_ids),
            # Лимит контейнера: без него «1200 МБ» ничего не говорит — это может
            # быть и половина пресета, и его потолок.
            **{k: v for k, v in memory_snapshot().as_dict().items() if k != "rss_mb"},
        },
        min_interval_s=settings.WORKER_EVENT_THROTTLE_S,
    )


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
            # Заодно замеряем память по ходу задачи, а не только в её конце: если
            # процесс умрёт, последний замер останется единственным свидетельством
            # того, сколько он съел (в конце job писать будет уже некому).
            await _report_memory_if_high(rss_mb())
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001 — транзиентный сбой: логируем и продолжаем
            logger.warning("Heartbeat failed, will retry", job_id=job_id, error=str(e))
            # И в БД: именно непишущийся heartbeat выглядит в карточке как
            # «Обработчик молчит N минут» у живой задачи. Без этой записи «умер» и
            # «жив, но не может отчитаться» неотличимы.
            from app.models.system_event import KIND_WORKER_HEARTBEAT_FAILED

            await _record_event_throttled(
                KIND_WORKER_HEARTBEAT_FAILED,
                {
                    "job_id": job_id,
                    "worker_id": WORKER_ID,
                    "error": str(e)[:500],
                    "running": len(_inflight_job_ids),
                },
                min_interval_s=settings.WORKER_EVENT_THROTTLE_S,
            )


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
        # `_job_id` + `_job_attempt` в копии payload (саму запись не меняем):
        # обработчику нужно знать, какой именно прогон он ведёт, чтобы
        # остановиться, если задачу уже забрал кто-то другой.
        async with AsyncSessionLocal() as db:
            await handler(
                {**(job.payload or {}), "_job_id": job.id, "_job_attempt": job.attempts},
                db,
            )
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
                # И сказать об этом пользователю: молчаливая повторная попытка
                # выглядит как зависшая задача — прогресс замирает на прежнем шаге,
                # а причина остаётся в логе контейнера, куда он не смотрит.
                await job_queue.note_retry_on_task(
                    db,
                    (job.payload or {}).get("task_id"),
                    job.attempts,
                    settings.JOB_MAX_ATTEMPTS,
                    str(e),
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
    """Не брать НОВУЮ задачу, пока память высока и хоть одна уже считается.

    Жёсткое число слотов не знает, что взяло: четыре тяжёлые сметы валят процесс,
    четыре лёгких — нет. Тормоз делает параллельность адаптивной: под нагрузкой
    задачи идут по одной, в спокойное время занимаются все слоты. Задачи не
    теряются — ждут в очереди.

    Три независимых предохранителя:
    - ЗАПАС памяти (главный): при личном лимите контейнера это «лимит минус
      занятое», без лимита — MemAvailable машины. Второе важно: 30.07.2026
      выяснилось, что на контейнере лимита нет и 3,9 ГБ делят web с обработчиком,
      поэтому доля «от лимита» без MemAvailable ничего не значила;
    - доля от лимита — работает, когда лимит контейнеру задан;
    - прежний абсолютный порог RSS — резерв там, где нет ни того, ни другого.

    Пустой процесс не тормозим никогда: иначе высокая база (загруженный прайс,
    матрицы эмбеддингов) заперла бы очередь навсегда — брать было бы нечего, а
    память сама не упадёт.
    """
    if not _inflight_job_ids:
        return False

    snap = memory_snapshot()
    min_free = settings.WORKER_MEM_MIN_FREE_MB
    headroom = snap.headroom_mb
    if min_free > 0 and headroom is not None and headroom < min_free:
        logger.info(
            "Memory brake — новую задачу не берём (мало свободной памяти)",
            running=len(_inflight_job_ids), headroom_mb=headroom, min_free_mb=min_free,
            **snap.as_dict(),
        )
        return True

    ratio_limit = settings.WORKER_MEM_HIGH_RATIO
    if ratio_limit > 0 and snap.ratio is not None and snap.ratio >= ratio_limit:
        logger.info(
            "Memory brake — новую задачу не берём (доля лимита контейнера)",
            running=len(_inflight_job_ids), **snap.as_dict(),
        )
        return True

    limit = settings.WORKER_RSS_PAUSE_MB
    if limit > 0 and snap.rss_mb is not None and snap.rss_mb >= limit:
        logger.info(
            "Memory brake — новую задачу не берём (порог RSS)",
            rss_mb=snap.rss_mb, limit_mb=limit, running=len(_inflight_job_ids),
        )
        return True
    return False


def _claim_stagger_blocked() -> bool:
    """Не брать вторую задачу, пока первая младше WORKER_CLAIM_STAGGER_S.

    Тормоз по памяти смотрит на ТЕКУЩУЮ занятость, а очередь опрашивается раз в
    2 секунды: три возобновлённые задачи захватывались почти одновременно — когда
    память первой ещё не выросла, — и тормоз не срабатывал ни разу. Контейнер
    получал OOM-kill, а задачи висели «в обработке». Разнос даёт памяти первой
    задачи проявиться до захвата второй.

    Слот при этом не занимается: задачи ждут в очереди и никуда не деваются.
    """
    gap = settings.WORKER_CLAIM_STAGGER_S
    if gap <= 0 or not _inflight_started_at:
        return False
    youngest_age = _monotonic() - max(_inflight_started_at.values())
    if youngest_age >= gap:
        return False
    logger.info(
        "Claim stagger — новую задачу берём не раньше чем через паузу",
        youngest_age_s=round(youngest_age, 1),
        stagger_s=gap,
        running=len(_inflight_job_ids),
    )
    return True


def _duplicate_task_id(job: Job) -> Optional[str]:
    """task_id, если эту задачу прямо сейчас уже считает этот же процесс.

    None — дубля нет. Проверка в памяти процесса и потому надёжная: обработчик в
    контейнере один, и второй прогон той же задачи — всегда ошибка (реклейм принял
    голодающий по процессору прогон за мёртвый).
    """
    task_id = (job.payload or {}).get("task_id")
    if not task_id:
        return None
    return task_id if task_id in _inflight_task_ids.values() else None


def _cpu_slots_cap() -> Optional[int]:
    """Сколько задач разом отпускает процессор. None — число ядер неизвестно.

    Одно ядро оставляем не воркеру: web живёт на той же машине, и когда обработчик
    занимает все ядра (эмбеддинги — чистый счёт), интерфейс перестаёт отвечать —
    30.07.2026 страница задачи не загружалась вовсе, хотя обработчик был жив.
    """
    cores = os.cpu_count()
    if not cores:
        return None
    return max(1, cores - 1)


def _effective_slots() -> int:
    """Сколько задач этот обработчик реально может считать разом.

    `WORKER_CONCURRENCY` — потолок, заданный человеком; свободная память — физика.
    Берём меньшее из двух: на тесном сервере четыре слота означают OOM-kill, а не
    производительность.

    Бюджет считаем по-разному, и это важно: с личным лимитом контейнера — «доля
    лимита минус занятое»; без лимита (общая машина, как на Timeweb 30.07.2026) —
    MemAvailable минус неприкосновенный запас, потому что остальную память
    занимают соседи по машине, а не мы. Цифр нет вовсе (локально, macOS) →
    поведение как раньше.
    """
    configured = max(1, settings.WORKER_CONCURRENCY)
    cpu_cap = _cpu_slots_cap()
    if cpu_cap is not None and cpu_cap < configured:
        logger.warning(
            "Слотов меньше настроенного — столько отпускает процессор",
            slots=cpu_cap, configured=configured, cores=os.cpu_count(),
        )
        configured = cpu_cap

    snap = memory_snapshot()
    per_task = settings.WORKER_TASK_MEM_MB
    ratio = settings.WORKER_MEM_HIGH_RATIO
    # ratio<=0 — механизм памяти выключен целиком (как и тормоз): в этом случае
    # считать слоты «от нулевого запаса» и оставлять один было бы не отключением,
    # а самым жёстким ограничением.
    if per_task <= 0 or ratio <= 0:
        return configured

    if snap.limit_source == "cgroup" and snap.limit_mb:
        budget = snap.limit_mb * ratio - (snap.used_mb or 0.0)
    elif snap.available_mb is not None:
        budget = snap.available_mb - max(0, settings.WORKER_MEM_MIN_FREE_MB)
    else:
        return configured

    by_memory = max(1, int(budget // per_task))
    slots = min(configured, by_memory)
    if slots != configured:
        logger.warning(
            "Слотов меньше настроенного — столько отпускает свободная память",
            slots=slots, configured=configured, per_task_mb=per_task,
            budget_mb=round(budget, 1), **snap.as_dict(),
        )
    return slots


async def _poll_loop(sem: asyncio.Semaphore, inflight: set) -> None:
    while not _shutdown.is_set():
        await sem.acquire()
        if _shutdown.is_set():
            sem.release()
            break
        if _memory_brake_engaged() or _claim_stagger_blocked():
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

        # Дубль живого прогона этой же задачи не запускаем ни при каких условиях:
        # два прогона пишут в одну задачу, вдвое жгут процессор и ДВАЖДЫ платят за
        # запросы к ИИ. Снимаем дубль и идём дальше за следующей job.
        dup_task_id = _duplicate_task_id(job)
        if dup_task_id is not None:
            try:
                async with AsyncSessionLocal() as db:
                    await job_queue.drop_duplicate_job(db, job.id, dup_task_id)
            except Exception as e:  # noqa: BLE001 — снятие дубля не важнее работы
                logger.warning("Duplicate job not dropped", job_id=job.id, error=str(e))
            sem.release()
            continue

        # Отмечаем задачу занятой СРАЗУ, а не внутри созданной ниже задачи:
        # `await sem.acquire()` на свободном слоте не отдаёт управление циклу,
        # поэтому следующий виток claim'а успел бы пройти раньше, чем корутина
        # начнётся, — и тормоз по памяти с разносом захватов видели бы пустой
        # процесс. Ровно так три задачи и захватывались за секунды.
        _inflight_job_ids.add(job.id)
        _inflight_started_at[job.id] = _monotonic()
        job_task_id = (job.payload or {}).get("task_id")
        if job_task_id:
            _inflight_task_ids[job.id] = job_task_id

        async def _run_and_release(j: Job) -> None:
            try:
                await run_job(j)
            finally:
                _inflight_job_ids.discard(j.id)
                _inflight_started_at.pop(j.id, None)
                _inflight_task_ids.pop(j.id, None)
                sem.release()

        task = asyncio.create_task(_run_and_release(job))
        inflight.add(task)
        task.add_done_callback(inflight.discard)


# ---------------------------------------------------------------------------
# Планировщик обслуживания (reclaim + поллеры)
# ---------------------------------------------------------------------------

async def _reclaim_job() -> None:
    async with AsyncSessionLocal() as db:
        # Сначала — job мёртвого процесса нашего же хоста: их не надо ждать 15
        # минут, обработчика за ними точно нет (см. reclaim_crashed_worker_jobs).
        crashed = await job_queue.reclaim_crashed_worker_jobs(
            db, WORKER_ID, settings.WORKER_CRASH_RECLAIM_AGE_S
        )
        n = await job_queue.reclaim_stale(
            db, settings.JOB_VISIBILITY_TIMEOUT_S, settings.JOB_MAX_ATTEMPTS
        )
    if crashed:
        logger.warning("Requeued jobs left by dead worker process", count=crashed)
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


async def _sync_api_cost_job() -> None:
    """Сверить траты с официальным отчётом Anthropic (раз в час).

    Час, а не минута: отчёт отдаёт дневные бакеты, и чаще их перечитывать нечего
    (документация просит не полить чаще раза в минуту даже там, где это нужно).
    Свежесть остатка обеспечивает не эта сверка, а собственный журнал вызовов —
    здесь только уточнение уже закрытых дней.

    Отказ Anthropic не роняет обработчик: остаток продолжает считаться по своему
    журналу, а на странице «Система» видно время последней удачной сверки.
    """
    from app.services import balance_service
    from app.services.anthropic_admin import AdminApiError, is_configured

    if not is_configured():
        return  # админ-ключ не задан — официальной сверки нет, и это норма
    try:
        async with AsyncSessionLocal() as db:
            await balance_service.sync_cost_days(db)
    except AdminApiError as exc:
        logger.warning("Cost report sync failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001 — фоновой job не имеет права падать
        logger.warning("Cost report sync crashed", error=str(exc))


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
    scheduler.add_job(_sync_api_cost_job, "interval", hours=1, max_instances=1)
    return scheduler


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def _announce_start(slots: int) -> int:
    """Записать факт старта обработчика и подобрать job мёртвого предшественника.

    Зачем событие: web — другой контейнер, лога Timeweb пользователь не видит, и
    смерть обработчика до сих пор не была видна НИГДЕ. При OOM-kill жалоба на
    память не пишется (процесс убит мгновенно), поэтому единственная надёжная
    улика — сам факт незапланированного старта. Череда таких строк в диагностике
    админки = «контейнер умирает от памяти», и спор «сколько задач параллельно»
    впервые опирается на цифры.

    Возвращает число job, возвращённых в очередь за упавшим процессом.
    """
    from app.models.system_event import KIND_WORKER_STARTED, SystemEvent

    requeued = 0
    snap = memory_snapshot()
    try:
        async with AsyncSessionLocal() as db:
            requeued = await job_queue.reclaim_crashed_worker_jobs(
                db, WORKER_ID, settings.WORKER_CRASH_RECLAIM_AGE_S
            )
            db.add(
                SystemEvent(
                    kind=KIND_WORKER_STARTED,
                    payload={
                        "worker_id": WORKER_ID,
                        "slots": slots,
                        "configured_concurrency": settings.WORKER_CONCURRENCY,
                        "requeued": requeued,
                        **snap.as_dict(),
                    },
                )
            )
            await db.commit()
    except Exception as e:  # noqa: BLE001 — на первом деплое БД может быть не готова
        logger.warning("Worker start not recorded", error=str(e))
    return requeued


async def main() -> None:
    logger.info("Worker starting", worker_id=WORKER_ID)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _shutdown.set)
        except NotImplementedError:
            pass  # Windows

    # ДО poll-loop: первая же job должна видеть прайс, иначе смета считается без
    # корпоративных цен и уходит целиком в ИИ.
    await _warm_price_cache()

    # Слоты считаем ПОСЛЕ прогрева: прайс в памяти — это база, от которой зависит,
    # сколько задач ещё влезает под лимит контейнера.
    slots = _effective_slots()
    logger.info(
        "Worker ready",
        worker_id=WORKER_ID,
        slots=slots,
        configured_concurrency=settings.WORKER_CONCURRENCY,
        **memory_snapshot().as_dict(),
    )
    sem = asyncio.Semaphore(slots)
    inflight: set = set()

    # До poll-loop: job мёртвого предшественника надо вернуть в очередь раньше,
    # чем начнём брать новые.
    await _announce_start(slots)

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

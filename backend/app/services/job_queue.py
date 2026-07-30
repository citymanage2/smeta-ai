"""Durable-очередь на таблице `jobs`: enqueue / claim / heartbeat / complete / fail / reclaim.

Claim-паттерн: короткая атомарная транзакция (не держим row-lock всю длинную задачу).
Корректность (не отдать одну job двум воркерам) обеспечивается двумя слоями:
- на PostgreSQL — `FOR UPDATE SKIP LOCKED` в выборе кандидата (воркеры не конкурируют);
- на любом диалекте — guard `UPDATE ... WHERE status='queued'` + проверка rowcount==1
  (гонка проигравшего воркера ничего не портит — он просто берёт следующую).

Fairness (round-robin по владельцу): кандидат — из владельца с наименьшим числом
running-job; тай-брейк priority DESC, created_at ASC.

Связь с доменным слоем: `jobs.status` — транспорт, `tasks.status` — то, что видит
пользователь. Терминальные переходы транспорта ОБЯЗАНЫ отражаться в домене, иначе
задача навсегда виснет в «Обработке» (см. plans/2026-07-29-osirotevshie-zadachi-v-obrabotke.md).
"""
from datetime import datetime, timezone, timedelta
from typing import Iterable, Optional

import structlog
from sqlalchemy import select, update, func
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.task import Task

logger = structlog.get_logger()

# Статусы задачи, при которых она считается «в работе»: только их и вправе
# перевести в failed слой очереди. Guard защищает от гонки — завершившуюся,
# отменённую или поставленную на паузу задачу мы не портим.
ACTIVE_TASK_STATUSES = ("pending", "processing")

# Batch-режим: задача штатно живёт БЕЗ своей job (пачка считается на серверах
# Anthropic, досчитывает batch_poller). Единственное значение `_stage`, при
# котором отсутствие job — норма, а не сирота.
_BATCH_PENDING_STAGE = "batch_pending"

# Тексты для пользователя, не для лога: менеджер должен понять, что делать.
_ERR_JOB_FAILED = "Обработка прервана и не возобновилась. Запустите задачу заново."
_ERR_MAX_ATTEMPTS = (
    "Обработка прерывалась несколько раз подряд (обычно из-за перезапуска сервиса) "
    "и была остановлена. Запустите задачу заново."
)
_ERR_ORPHANED = (
    "Обработка прервалась и не возобновилась — задача больше не выполняется. "
    "Запустите её заново."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _fail_linked_tasks(db: AsyncSession, task_ids: Iterable[Optional[str]], error: str) -> int:
    """Пометить задачи failed. Guard по статусу — не трогаем уже завершённые.

    Не коммитит: вызывающий сам решает границы транзакции.
    """
    ids = [t for t in task_ids if t]
    if not ids:
        return 0
    res = await db.execute(
        update(Task)
        .where(Task.id.in_(ids), Task.status.in_(ACTIVE_TASK_STATUSES))
        .values(status="failed", error_message=error[:1000])
    )
    n = res.rowcount or 0
    if n:
        logger.info("Tasks marked failed by queue layer", count=n, task_ids=ids)
    return n


def _is_postgres(db: AsyncSession) -> bool:
    try:
        return db.bind.dialect.name == "postgresql"
    except Exception:
        return False


async def enqueue(
    db: AsyncSession,
    kind: str,
    payload: dict,
    owner_id: Optional[int] = None,
    priority: int = 0,
) -> Job:
    """Поставить job в очередь. Коммитит."""
    job = Job(kind=kind, payload=payload, owner_id=owner_id, priority=priority, status="queued")
    db.add(job)
    await db.commit()
    await db.refresh(job)
    logger.info("Job enqueued", job_id=job.id, kind=kind, owner_id=owner_id)
    return job


async def claim_one(db: AsyncSession, worker_id: str, max_tries: int = 5) -> Optional[Job]:
    """Атомарно захватить одну queued-job (round-robin по владельцу). Коммитит.

    Возвращает захваченную Job или None, если очередь пуста.
    """
    running = aliased(Job)
    # Число running-job у того же владельца — мера «занятости» владельца.
    running_ct = (
        select(func.count(running.id))
        .where(running.owner_id == Job.owner_id, running.status == "running")
        .correlate(Job)
        .scalar_subquery()
    )

    for _ in range(max_tries):
        candidate = (
            select(Job.id)
            .where(Job.status == "queued")
            .order_by(running_ct.asc(), Job.priority.desc(), Job.created_at.asc())
            .limit(1)
        )
        if _is_postgres(db):
            # Воркеры не конкурируют за одну строку: занятые пропускаются.
            candidate = candidate.with_for_update(skip_locked=True)

        job_id = (await db.execute(candidate)).scalar_one_or_none()
        if job_id is None:
            await db.rollback()
            return None

        # Guard по status='queued': если строку уже забрал другой воркер (без SKIP
        # LOCKED), rowcount==0 → пробуем следующую.
        res = await db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(
                status="running",
                claimed_by=worker_id,
                claimed_at=_now(),
                attempts=Job.attempts + 1,
            )
        )
        if res.rowcount == 1:
            # Читаем строку ДО commit (в той же транзакции). Если re-fetch упадёт
            # (обрыв соединения), claim откатится и job останется queued — не
            # осиротеет в running без обработчика (P3-a).
            # populate_existing: если эта же job уже лежит в identity map сессии,
            # обычный SELECT вернул бы её ПРЕЖНИЕ атрибуты — в частности старый
            # attempts, по которому решается «исчерпаны ли попытки» и какое
            # поколение прогона идёт. В проде каждый claim берёт свежую сессию, но
            # полагаться на это нельзя.
            claimed = (
                await db.execute(
                    select(Job).where(Job.id == job_id).execution_options(populate_existing=True)
                )
            ).scalar_one()
            await db.commit()
            logger.info("Job claimed", job_id=job_id, worker=worker_id, attempts=claimed.attempts)
            return claimed

        await db.rollback()  # проиграли гонку — следующая попытка

    return None


async def live_heartbeat_age_s(db: AsyncSession, task_id: str) -> Optional[float]:
    """Сколько секунд прошло с последнего сигнала обработчика этой задачи.

    `claimed_at` running-job продлевается `heartbeat()`, поэтому его возраст —
    честный признак жизни процесса: свежий = задача обрабатывается, старый =
    обработчик умер или застрял. Отдаётся в карточку задачи, чтобы пользователь
    видел разницу между «работает» и «висит» (раньше heartbeat писался только
    в лог сервера и наружу не выходил).

    None — сигнала нет: живой job нет вовсе, либо она ещё `queued` (не захвачена,
    `claimed_at` пуст). Ноль в этом случае был бы ложью про живость.

    Фильтр по `payload.task_id` — на стороне Python: JSON-предикаты
    диалектозависимы (JSONB в проде, JSON в SQLite), а running-job единицы.
    Тот же приём в `sweep_orphaned_tasks`.
    """
    rows = (
        await db.execute(
            select(Job.payload, Job.claimed_at).where(Job.status == "running")
        )
    ).all()

    claimed = [
        c for payload, c in rows
        if c is not None and (payload or {}).get("task_id") == task_id
    ]
    if not claimed:
        return None

    # Задачу может вести только одна job, но при реклейме кратко бывает две —
    # берём самый свежий сигнал: живость определяет лучший из имеющихся.
    return _age_s(max(claimed))


def _age_s(dt: datetime) -> float:
    """Возраст в секундах; naive-даты (SQLite) трактуем как UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (_now() - dt).total_seconds())


async def heartbeat(db: AsyncSession, job_id: int) -> None:
    """Продлить визибилити running-job (сдвинуть claimed_at на now)."""
    await db.execute(
        update(Job).where(Job.id == job_id, Job.status == "running").values(claimed_at=_now())
    )
    await db.commit()


async def complete(db: AsyncSession, job_id: int) -> None:
    """Пометить job выполненной."""
    await db.execute(update(Job).where(Job.id == job_id).values(status="done"))
    await db.commit()


async def fail(db: AsyncSession, job_id: int, error: str) -> None:
    """Терминально пометить job failed (без ретрая) и уронить связанную задачу.

    Без второго шага задача осталась бы в `processing` навсегда: собственный
    except-обработчик `TaskProcessor` не выполняется, если процесс убит.
    """
    await db.execute(
        update(Job).where(Job.id == job_id).values(status="failed", last_error=(error or "")[:1000])
    )
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is not None:
        detail = f" Причина: {error}" if error else ""
        await _fail_linked_tasks(
            db, [(job.payload or {}).get("task_id")], _ERR_JOB_FAILED + detail
        )
    await db.commit()


async def reclaim_stale(db: AsyncSession, timeout_s: int, max_attempts: int) -> int:
    """Вернуть в очередь зависшие running-job (claimed_at старше timeout).

    Если attempts исчерпаны — job → failed. Возвращает число обработанных job.
    Заменяет _recover_stuck_tasks: после рестарта worker висящие job подхватятся.

    Оба перехода — АТОМАРНЫЕ guarded-UPDATE с предикатом `status='running'`
    (а не read-modify-write). Это исключает воскрешение только что завершённой
    job: если параллельный complete()/fail() успел перевести её в done/failed,
    WHERE status='running' не совпадёт и reclaim её не тронет (P0-A).
    """
    cutoff = _now() - timedelta(seconds=timeout_s)

    # Исчерпаны попытки → терминальный failed. Payload нужен, чтобы уронить и
    # связанную задачу, поэтому читаем кандидатов отдельным SELECT, а не через
    # UPDATE..RETURNING: с ORM-enabled UPDATE состав RETURNING зависит от стратегии
    # synchronize_session и диалекта, а отключение синхронизации оставляет в сессии
    # протухшие объекты. Здесь важна предсказуемость на обоих диалектах.
    stale_exhausted = (
        await db.execute(
            select(Job.id, Job.payload).where(
                Job.status == "running",
                Job.claimed_at < cutoff,
                Job.attempts >= max_attempts,
            )
        )
    ).all()
    n_failed = 0
    if stale_exhausted:
        ids = [jid for jid, _ in stale_exhausted]
        # Guard `status='running'` сохраняет атомарность: параллельно завершённую
        # job UPDATE не тронет. Её задача при этом уже переведена в терминальный
        # статус самим обработчиком, поэтому guard в _fail_linked_tasks не даст
        # испортить её и в этом узком окне.
        res = await db.execute(
            update(Job)
            .where(Job.id.in_(ids), Job.status == "running")
            .values(status="failed", last_error="Превышено число попыток (reclaim)")
        )
        n_failed = res.rowcount or 0
        if n_failed:
            await _fail_linked_tasks(
                db, [(p or {}).get("task_id") for _, p in stale_exhausted], _ERR_MAX_ATTEMPTS
            )
    # Ещё есть попытки → назад в очередь.
    requeued = await db.execute(
        update(Job)
        .where(
            Job.status == "running",
            Job.claimed_at < cutoff,
            Job.attempts < max_attempts,
        )
        .values(status="queued", claimed_by=None, claimed_at=None)
    )

    n_requeued = requeued.rowcount or 0
    count = n_failed + n_requeued
    if count:
        await db.commit()
        logger.info("Reclaimed stale jobs", requeued=n_requeued, failed=n_failed)
    # count==0 → изменений нет; транзакцию закроет владелец сессии (async with).
    return count


async def reclaim_crashed_worker_jobs(
    db: AsyncSession, worker_id: str, min_age_s: int
) -> int:
    """Вернуть в очередь job, захваченные умершим процессом НА ЭТОМ ЖЕ хосте.

    Обработчик в контейнере один, а `claimed_by` = `hostname:pid`. Значит
    running-job, помеченная нашим хостом, но ЧУЖИМ pid — это работа процесса,
    которого на хосте больше нет: контейнер получил OOM-kill (или иначе умер) и
    поднялся заново. Ждать `JOB_VISIBILITY_TIMEOUT_S` (15 мин) в этом случае
    бессмысленно — задача точно брошена, и ровно эти 15 минут пользователь видел
    как «висит вечно» (см. plans/2026-07-30-parallelnaya-obrabotka-umiraet.md).

    `min_age_s` (заведомо больше интервала heartbeat) — страховка на случай, если
    платформа выдаст двум живым контейнерам одинаковый hostname: у живого соседа
    heartbeat свежий, и его job мы не тронем.

    Попытку НЕ возвращаем: смерть процесса — это сбой обработки, в отличие от
    планового рестарта (там `requeue_after_shutdown` компенсирует инкремент).
    Иначе бесконечный OOM-цикл крутился бы вечно вместо честного `failed`.
    """
    host = (worker_id or "").split(":")[0]
    if not host:
        return 0
    cutoff = _now() - timedelta(seconds=min_age_s)

    res = await db.execute(
        update(Job)
        .where(
            Job.status == "running",
            Job.claimed_by.is_not(None),
            Job.claimed_by != worker_id,
            Job.claimed_by.startswith(f"{host}:", autoescape=True),
            Job.claimed_at < cutoff,
        )
        .values(status="queued", claimed_by=None, claimed_at=None)
    )
    n = res.rowcount or 0
    if n:
        await db.commit()
        logger.warning(
            "Requeued jobs of dead worker process on this host",
            count=n,
            worker=worker_id,
            min_age_s=min_age_s,
        )
    return n


async def sweep_orphaned_tasks(db: AsyncSession, grace_s: int) -> int:
    """Уронить задачи «в работе», за которыми не стоит ни одна живая job.

    Второй эшелон после `fail()`/`reclaim_stale()`: ловит случаи, до которых те не
    дотягиваются — потерянная запись job, сироты, накопленные до этого механизма.
    Без него задача висит в «Обработке» вечно, показывая пользователю ложный
    прогресс. Возвращает число помеченных задач.

    Кого НЕ трогаем:
    - свежие (updated_at внутри grace) — job могла ещё не быть захвачена;
    - `_stage='batch_pending'` — batch by design живёт без job, досчитает поллер;
    - `paused` (ждёт пополнения баланса) и терминальные — не в ACTIVE_TASK_STATUSES;
    - удалённые (`deleted_at`).
    """
    cutoff = _now() - timedelta(seconds=grace_s)

    candidates = (
        await db.execute(
            select(Task.id, Task.progress_data).where(
                Task.status.in_(ACTIVE_TASK_STATUSES),
                Task.updated_at < cutoff,
                Task.deleted_at.is_(None),
            )
        )
    ).all()
    # Фильтр по progress_data — на стороне Python: JSON-предикаты диалектозависимы,
    # а кандидатов единицы (задачи «в работе»). Тот же приём в batch_poller.
    ids = [
        tid
        for tid, pdata in candidates
        if (pdata or {}).get("_stage") != _BATCH_PENDING_STAGE
    ]
    if not ids:
        return 0

    live_payloads = (
        await db.execute(select(Job.payload).where(Job.status.in_(("queued", "running"))))
    ).scalars().all()
    live_task_ids = {(p or {}).get("task_id") for p in live_payloads}

    orphans = [tid for tid in ids if tid not in live_task_ids]
    if not orphans:
        return 0

    n = await _fail_linked_tasks(db, orphans, _ERR_ORPHANED)
    if n:
        await db.commit()
        logger.info("Swept orphaned tasks", count=n)
    return n


async def cancel_pending_jobs_for_task(db: AsyncSession, task_id: str) -> int:
    """Снять с очереди ещё не взятые job отменённой задачи. Коммитит.

    Без этого «Стоп» красил только `tasks.status`: queued-job оставалась в очереди,
    рано или поздно её забирал worker, а `TaskProcessor.process()` первым делом
    ставил `processing` — и отменённая задача воскресала, занимая слот и деньги.
    Ровно это пользователь видел как «очистила очередь, а задачи всё равно висят».

    Running-job НЕ трогаем: её обработчик сам заметит отмену на ближайшем чекпоинте
    (`TaskProcessor._check_cancelled`) и завершится штатно. Снять её здесь значило бы
    оставить задачу «в работе» без записи в очереди — и `sweep_orphaned_tasks`
    пометил бы её failed поверх честного `cancelled`.

    Фильтр по `payload.task_id` — на стороне Python: JSON-предикаты диалектозависимы
    (JSONB в проде, JSON в SQLite). Тот же приём в `live_heartbeat_age_s`.
    """
    rows = (
        await db.execute(select(Job.id, Job.payload).where(Job.status == "queued"))
    ).all()
    ids = [jid for jid, payload in rows if (payload or {}).get("task_id") == task_id]
    if not ids:
        return 0

    # Guard `status='queued'`: job, которую worker забрал прямо сейчас, не портим —
    # её остановит проверка отмены внутри обработчика.
    res = await db.execute(
        update(Job)
        .where(Job.id.in_(ids), Job.status == "queued")
        .values(status="cancelled", last_error="Остановлено пользователем")
    )
    n = res.rowcount or 0
    if n:
        await db.commit()
        logger.info("Queued jobs cancelled with task", count=n, task_id=task_id)
    return n


async def supersede_jobs_for_task(db: AsyncSession, task_id: str) -> int:
    """Снять ВСЕ живые job задачи перед новым прогоном («Перезапустить»). Коммитит.

    Отличие от `cancel_pending_jobs_for_task`: здесь снимается и `running`. Так
    надо, потому что перезапускают обычно как раз висящую задачу: старая job
    остаётся в очереди, и рестарт добавлял ВТОРУЮ — два прогона считали одну
    задачу параллельно, писали друг поверх друга и оплачивали запросы дважды.

    Прежний прогон, если он ещё жив, увидит, что его job больше не `running`
    (`TaskProcessor._check_cancelled`), и выйдет на ближайшем чекпоинте.
    """
    rows = (
        await db.execute(
            select(Job.id, Job.payload).where(Job.status.in_(("queued", "running")))
        )
    ).all()
    ids = [jid for jid, payload in rows if (payload or {}).get("task_id") == task_id]
    if not ids:
        return 0

    res = await db.execute(
        update(Job)
        .where(Job.id.in_(ids), Job.status.in_(("queued", "running")))
        .values(status="superseded", last_error="Заменена новым прогоном (перезапуск)")
    )
    n = res.rowcount or 0
    if n:
        await db.commit()
        logger.info("Jobs superseded by restart", count=n, task_id=task_id)
    return n


async def requeue_after_shutdown(
    db: AsyncSession, job_ids: Iterable[int], worker_id: str
) -> int:
    """Вернуть в очередь недоигранные job при штатной остановке, НЕ списав попытку.

    Плановый рестарт (деплой) — не сбой обработки, и не должен расходовать бюджет
    ретраев: длинная задача иначе не переживает трёх деплоев подряд и умирает по
    `attempts >= JOB_MAX_ATTEMPTS`. `attempts - 1` компенсирует инкремент, сделанный
    в `claim_one`.

    Guard'ы: только свои (`claimed_by == worker_id`) и только всё ещё `running` —
    успевшую завершиться в дренаже job не воскрешаем.
    """
    ids = list(job_ids)
    if not ids:
        return 0
    res = await db.execute(
        update(Job)
        .where(
            Job.id.in_(ids),
            Job.status == "running",
            Job.claimed_by == worker_id,
            Job.attempts > 0,
        )
        .values(status="queued", claimed_by=None, claimed_at=None, attempts=Job.attempts - 1)
    )
    n = res.rowcount or 0
    if n:
        await db.commit()
        logger.info("Requeued jobs after shutdown", count=n, worker=worker_id)
    return n

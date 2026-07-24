"""Durable-очередь на таблице `jobs`: enqueue / claim / heartbeat / complete / fail / reclaim.

Claim-паттерн: короткая атомарная транзакция (не держим row-lock всю длинную задачу).
Корректность (не отдать одну job двум воркерам) обеспечивается двумя слоями:
- на PostgreSQL — `FOR UPDATE SKIP LOCKED` в выборе кандидата (воркеры не конкурируют);
- на любом диалекте — guard `UPDATE ... WHERE status='queued'` + проверка rowcount==1
  (гонка проигравшего воркера ничего не портит — он просто берёт следующую).

Fairness (round-robin по владельцу): кандидат — из владельца с наименьшим числом
running-job; тай-брейк priority DESC, created_at ASC.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog
from sqlalchemy import select, update, func
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job

logger = structlog.get_logger()


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
            claimed = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
            await db.commit()
            logger.info("Job claimed", job_id=job_id, worker=worker_id, attempts=claimed.attempts)
            return claimed

        await db.rollback()  # проиграли гонку — следующая попытка

    return None


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
    """Терминально пометить job failed (без ретрая)."""
    await db.execute(
        update(Job).where(Job.id == job_id).values(status="failed", last_error=(error or "")[:1000])
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

    # Исчерпаны попытки → терминальный failed.
    failed = await db.execute(
        update(Job)
        .where(
            Job.status == "running",
            Job.claimed_at < cutoff,
            Job.attempts >= max_attempts,
        )
        .values(status="failed", last_error="Превышено число попыток (reclaim)")
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

    n_failed = failed.rowcount or 0
    n_requeued = requeued.rowcount or 0
    count = n_failed + n_requeued
    if count:
        await db.commit()
        logger.info("Reclaimed stale jobs", requeued=n_requeued, failed=n_failed)
    # count==0 → изменений нет; транзакцию закроет владелец сессии (async with).
    return count

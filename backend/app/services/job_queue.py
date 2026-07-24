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
            await db.commit()
            claimed = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one()
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
    """
    cutoff = _now() - timedelta(seconds=timeout_s)
    stale = (
        await db.execute(
            select(Job).where(Job.status == "running", Job.claimed_at < cutoff)
        )
    ).scalars().all()

    count = 0
    for job in stale:
        if job.attempts >= max_attempts:
            job.status = "failed"
            job.last_error = f"Превышено число попыток ({job.attempts})"
            logger.warning("Job exhausted attempts", job_id=job.id, attempts=job.attempts)
        else:
            job.status = "queued"
            job.claimed_by = None
            job.claimed_at = None
            logger.info("Job reclaimed", job_id=job.id, attempts=job.attempts)
        count += 1
    if count:
        await db.commit()
    return count

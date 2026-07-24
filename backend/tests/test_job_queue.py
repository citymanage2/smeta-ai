"""Тесты durable-очереди job_queue: claim без дублей, round-robin, reclaim."""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import delete, select, update

from app.models.job import Job
from app.services import job_queue

pytestmark = pytest.mark.asyncio


async def _clear(db):
    await db.execute(delete(Job))
    await db.commit()


async def test_enqueue_and_claim(db_session):
    await _clear(db_session)
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": "t1"}, owner_id=1)
    assert job.status == "queued"

    claimed = await job_queue.claim_one(db_session, "worker-A")
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == "running"
    assert claimed.claimed_by == "worker-A"
    assert claimed.attempts == 1


async def test_no_double_claim(db_session):
    await _clear(db_session)
    await job_queue.enqueue(db_session, "task.process", {"task_id": "only"}, owner_id=1)

    first = await job_queue.claim_one(db_session, "worker-A")
    second = await job_queue.claim_one(db_session, "worker-B")
    assert first is not None
    # Вторая попытка не отдаёт ту же (уже running) job.
    assert second is None


async def test_round_robin_by_owner(db_session):
    await _clear(db_session)
    # Владелец 1 ставит две задачи раньше, владелец 2 — одну позже.
    a1 = await job_queue.enqueue(db_session, "task.process", {"n": "a1"}, owner_id=1)
    a2 = await job_queue.enqueue(db_session, "task.process", {"n": "a2"}, owner_id=1)
    b1 = await job_queue.enqueue(db_session, "task.process", {"n": "b1"}, owner_id=2)

    first = await job_queue.claim_one(db_session, "w1")
    # Оба владельца по 0 running → берётся самая старая (a1).
    assert first.id == a1.id

    second = await job_queue.claim_one(db_session, "w2")
    # У владельца 1 уже 1 running → честность отдаёт слот владельцу 2 (b1),
    # хотя a2 старше b1.
    assert second.id == b1.id
    assert second.id != a2.id


async def test_reclaim_requeues_stale(db_session):
    await _clear(db_session)
    job = await job_queue.enqueue(db_session, "task.process", {"n": "x"}, owner_id=1)
    await job_queue.claim_one(db_session, "w1")

    # Симулируем зависание: claimed_at далеко в прошлом.
    old = datetime.now(timezone.utc) - timedelta(seconds=2000)
    await db_session.execute(update(Job).where(Job.id == job.id).values(claimed_at=old))
    await db_session.commit()

    n = await job_queue.reclaim_stale(db_session, timeout_s=900, max_attempts=3)
    assert n == 1
    refreshed = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert refreshed.status == "queued"
    assert refreshed.claimed_by is None


async def test_reclaim_fails_after_max_attempts(db_session):
    await _clear(db_session)
    job = await job_queue.enqueue(db_session, "task.process", {"n": "y"}, owner_id=1)
    old = datetime.now(timezone.utc) - timedelta(seconds=2000)
    await db_session.execute(
        update(Job).where(Job.id == job.id).values(status="running", attempts=3, claimed_at=old)
    )
    await db_session.commit()

    n = await job_queue.reclaim_stale(db_session, timeout_s=900, max_attempts=3)
    assert n == 1
    refreshed = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert refreshed.status == "failed"


async def test_complete_and_fail(db_session):
    await _clear(db_session)
    j1 = await job_queue.enqueue(db_session, "task.process", {"n": "c"}, owner_id=1)
    j2 = await job_queue.enqueue(db_session, "task.process", {"n": "f"}, owner_id=1)

    await job_queue.complete(db_session, j1.id)
    await job_queue.fail(db_session, j2.id, "boom")

    r1 = (await db_session.execute(select(Job).where(Job.id == j1.id))).scalar_one()
    r2 = (await db_session.execute(select(Job).where(Job.id == j2.id))).scalar_one()
    assert r1.status == "done"
    assert r2.status == "failed"
    assert r2.last_error == "boom"

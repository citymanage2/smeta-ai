"""Сироты между `jobs` и `tasks`: задача навсегда зависает в «Обработке».

План: plans/2026-07-29-osirotevshie-zadachi-v-obrabotke.md
Исследование: thoughts/research/2026-07-29-orphaned-processing-tasks.md

Три слоя защиты:
1. терминальный failed у job → связанный Task помечается failed (Фаза 1);
2. периодический sweep задач без живой job (Фаза 2);
3. SIGTERM возвращает job в очередь, не сжигая попытку (Фаза 3).
"""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import delete, select, update

from app.models.job import Job
from app.models.task import Task
from app.services import job_queue

pytestmark = pytest.mark.asyncio


async def _clear(db):
    await db.execute(delete(Job))
    await db.execute(delete(Task))
    await db.commit()


@pytest.fixture(autouse=True)
async def _clean_db(db_session):
    """Тесты здесь коммитят, а фикстура сессии делает только rollback — без явной
    уборки ПОСЛЕ строки утекают в соседние файлы (падал test_admin_queue_health,
    который считает job'ы). Чистим с обеих сторон, чтобы порядок запуска не влиял.
    """
    await _clear(db_session)
    yield
    await _clear(db_session)


async def _task(db, *, status="processing", progress_data=None, age_min=60) -> Task:
    """Задача с искусственно состаренным updated_at (иначе не пройдёт grace)."""
    t = Task(
        user_role="user",
        task_type="LIST_FROM_GRAND",
        status=status,
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_data=progress_data,
    )
    db.add(t)
    await db.flush()
    old = datetime.now(timezone.utc) - timedelta(minutes=age_min)
    await db.execute(update(Task).where(Task.id == t.id).values(updated_at=old))
    await db.commit()
    await db.refresh(t)
    return t


async def _reload(db, task_id: str) -> Task:
    return (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()


# ── Фаза 1: терминальный failed у job → Task ────────────────────────────────


async def test_fail_marks_linked_task_failed(db_session):
    t = await _task(db_session)
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": t.id})

    await job_queue.fail(db_session, job.id, "boom")

    refreshed = await _reload(db_session, t.id)
    assert refreshed.status == "failed"
    assert refreshed.error_message  # текст для человека, а не пустая строка


async def test_fail_does_not_touch_completed_task(db_session):
    """Guard: задача успела завершиться — терминальная job её не портит."""
    t = await _task(db_session, status="completed")
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": t.id})

    await job_queue.fail(db_session, job.id, "boom")

    assert (await _reload(db_session, t.id)).status == "completed"


async def test_fail_without_task_id_is_noop(db_session):
    """kind=retrain ссылается не на Task — вызов не должен падать."""
    job = await job_queue.enqueue(db_session, "retrain", {"job_id": 7})

    await job_queue.fail(db_session, job.id, "boom")

    refreshed = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert refreshed.status == "failed"


async def test_reclaim_max_attempts_marks_task_failed(db_session):
    """Ровно сценарий инцидента: попытки исчерпаны, job → failed, Task не должен осиротеть."""
    t = await _task(db_session)
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": t.id})
    old = datetime.now(timezone.utc) - timedelta(seconds=2000)
    await db_session.execute(
        update(Job).where(Job.id == job.id).values(status="running", attempts=3, claimed_at=old)
    )
    await db_session.commit()

    n = await job_queue.reclaim_stale(db_session, timeout_s=900, max_attempts=3)

    assert n == 1
    assert (await _reload(db_session, t.id)).status == "failed"


async def test_reclaim_requeue_keeps_task_processing(db_session):
    """Попытки ещё есть — job вернулась в очередь, задача остаётся в работе."""
    t = await _task(db_session)
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": t.id})
    old = datetime.now(timezone.utc) - timedelta(seconds=2000)
    await db_session.execute(
        update(Job).where(Job.id == job.id).values(status="running", attempts=1, claimed_at=old)
    )
    await db_session.commit()

    await job_queue.reclaim_stale(db_session, timeout_s=900, max_attempts=3)

    assert (await _reload(db_session, t.id)).status == "processing"


# ── Фаза 2: sweep осиротевших задач ─────────────────────────────────────────


async def test_sweep_marks_orphan_failed(db_session):
    """Задача в processing, живой job нет — это сирота."""
    t = await _task(db_session)

    n = await job_queue.sweep_orphaned_tasks(db_session, grace_s=1800)

    assert n == 1
    refreshed = await _reload(db_session, t.id)
    assert refreshed.status == "failed"
    assert refreshed.error_message


async def test_sweep_skips_batch_pending(db_session):
    """Batch-задача живёт без job by design — её досчитает batch_poller."""
    t = await _task(db_session, progress_data={"_stage": "batch_pending", "batch_id": "b1"})

    n = await job_queue.sweep_orphaned_tasks(db_session, grace_s=1800)

    assert n == 0
    assert (await _reload(db_session, t.id)).status == "processing"


@pytest.mark.parametrize("job_status", ["queued", "running"])
async def test_sweep_skips_task_with_live_job(db_session, job_status):
    t = await _task(db_session)
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": t.id})
    await db_session.execute(update(Job).where(Job.id == job.id).values(status=job_status))
    await db_session.commit()

    n = await job_queue.sweep_orphaned_tasks(db_session, grace_s=1800)

    assert n == 0
    assert (await _reload(db_session, t.id)).status == "processing"


async def test_sweep_respects_grace(db_session):
    """Свежая задача внутри grace не трогается: job могла ещё не попасть в очередь."""
    t = await _task(db_session, age_min=1)

    n = await job_queue.sweep_orphaned_tasks(db_session, grace_s=1800)

    assert n == 0
    assert (await _reload(db_session, t.id)).status == "processing"


@pytest.mark.parametrize("status", ["paused", "completed", "failed", "cancelled"])
async def test_sweep_ignores_non_active_statuses(db_session, status):
    """paused ждёт пополнения баланса, остальные уже терминальны."""
    t = await _task(db_session, status=status)

    n = await job_queue.sweep_orphaned_tasks(db_session, grace_s=1800)

    assert n == 0
    assert (await _reload(db_session, t.id)).status == status


async def test_sweep_ignores_deleted_task(db_session):
    t = await _task(db_session)
    await db_session.execute(
        update(Task).where(Task.id == t.id).values(deleted_at=datetime.now(timezone.utc))
    )
    await db_session.commit()

    n = await job_queue.sweep_orphaned_tasks(db_session, grace_s=1800)

    assert n == 0


async def test_sweep_handles_done_job(db_session):
    """job отработала (done), а задача осталась в processing — тоже сирота."""
    t = await _task(db_session)
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": t.id})
    await job_queue.complete(db_session, job.id)

    n = await job_queue.sweep_orphaned_tasks(db_session, grace_s=1800)

    assert n == 1
    assert (await _reload(db_session, t.id)).status == "failed"


# ── Фаза 3: SIGTERM не сжигает попытку ──────────────────────────────────────


async def test_requeue_after_shutdown_returns_attempt(db_session):
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": "t1"})
    claimed = await job_queue.claim_one(db_session, "worker-A")
    assert claimed.attempts == 1

    n = await job_queue.requeue_after_shutdown(db_session, [job.id], "worker-A")

    assert n == 1
    refreshed = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert refreshed.status == "queued"
    assert refreshed.attempts == 0  # попытка возвращена, деплой её не сжёг
    assert refreshed.claimed_by is None
    assert refreshed.claimed_at is None


async def test_requeue_after_shutdown_skips_foreign_job(db_session):
    """Чужую job (её держит другой worker) не трогаем."""
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": "t2"})
    await job_queue.claim_one(db_session, "worker-B")

    n = await job_queue.requeue_after_shutdown(db_session, [job.id], "worker-A")

    assert n == 0
    refreshed = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert refreshed.status == "running"
    assert refreshed.attempts == 1


async def test_requeue_after_shutdown_skips_finished_job(db_session):
    """Job успела завершиться в дренаже — не воскрешаем."""
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": "t3"})
    await job_queue.claim_one(db_session, "worker-A")
    await job_queue.complete(db_session, job.id)

    n = await job_queue.requeue_after_shutdown(db_session, [job.id], "worker-A")

    assert n == 0
    refreshed = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert refreshed.status == "done"


async def test_requeue_after_shutdown_empty_list(db_session):
    assert await job_queue.requeue_after_shutdown(db_session, [], "worker-A") == 0

"""«Стоп» должен снимать задачу с очереди, а отменённая — не воскресать.

Регресс 29–30.07.2026: `POST /tasks/{id}/cancel` красил только `tasks.status`.
queued-job оставалась в очереди, worker забирал её позже, а
`TaskProcessor.process()` первым делом ставил `processing` — отменённая задача
возвращалась в «Обработку», занимала слот воркера и жгла деньги. Пользователь
видел это как «очистила очередь, а задачи всё равно висят».
"""
import pytest
from sqlalchemy import delete, select

from app.models.job import Job
from app.models.task import Task
from app.services import job_queue

pytestmark = pytest.mark.asyncio


async def _clear_jobs(db):
    await db.execute(delete(Job))
    await db.commit()


async def test_cancel_pending_jobs_removes_queued(db_session):
    """queued-job отменённой задачи уходит из очереди."""
    await _clear_jobs(db_session)
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": "T-1"}, owner_id=1)
    job_id = job.id  # id до commit'а внутри cancel: после него атрибут истекает

    n = await job_queue.cancel_pending_jobs_for_task(db_session, "T-1")

    assert n == 1
    db_session.expire_all()
    status = (await db_session.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
    assert status == "cancelled"
    # Снятую job worker больше не возьмёт.
    assert await job_queue.claim_one(db_session, "w1") is None


async def test_cancel_leaves_other_tasks_alone(db_session):
    """Чужие job не трогаем — иначе «Стоп» одной задачи гасил бы всю очередь."""
    await _clear_jobs(db_session)
    await job_queue.enqueue(db_session, "task.process", {"task_id": "T-1"}, owner_id=1)
    other = await job_queue.enqueue(db_session, "task.process", {"task_id": "T-2"}, owner_id=1)
    other_id = other.id

    await job_queue.cancel_pending_jobs_for_task(db_session, "T-1")

    db_session.expire_all()
    status = (await db_session.execute(select(Job.status).where(Job.id == other_id))).scalar_one()
    assert status == "queued"


async def test_cancel_does_not_touch_running(db_session):
    """running-job не снимаем: её остановит проверка отмены внутри обработчика.

    Снять её здесь — оставить задачу «в работе» без записи в очереди, и
    sweep_orphaned_tasks пометил бы её failed поверх честного cancelled.
    """
    await _clear_jobs(db_session)
    await job_queue.enqueue(db_session, "task.process", {"task_id": "T-1"}, owner_id=1)
    claimed = await job_queue.claim_one(db_session, "w1")
    assert claimed is not None
    claimed_id = claimed.id

    n = await job_queue.cancel_pending_jobs_for_task(db_session, "T-1")

    assert n == 0
    db_session.expire_all()
    status = (await db_session.execute(select(Job.status).where(Job.id == claimed_id))).scalar_one()
    assert status == "running"


async def test_cancelled_task_is_not_resurrected(db_session):
    """process() отменённую задачу не переводит в processing."""
    from app.services.task_processor import TaskProcessor

    task = Task(
        id="c0000000-0000-0000-0000-000000000001",
        task_type="LIST_FROM_GRAND",
        status="cancelled",
        owner_id=1,
        user_role="admin",
    )
    db_session.add(task)
    await db_session.commit()
    task_id = task.id

    await TaskProcessor(str(task_id), db_session).process()

    db_session.expire_all()
    status = (await db_session.execute(select(Task.status).where(Task.id == task_id))).scalar_one()
    assert status == "cancelled"


async def test_deleted_task_is_not_resurrected(db_session):
    """Задача в корзине тоже не должна оживать из очереди."""
    from datetime import datetime, timezone

    from app.services.task_processor import TaskProcessor

    task = Task(
        id="c0000000-0000-0000-0000-000000000002",
        task_type="LIST_FROM_GRAND",
        status="pending",
        owner_id=1,
        user_role="admin",
        deleted_at=datetime.now(timezone.utc),
    )
    db_session.add(task)
    await db_session.commit()
    task_id = task.id

    await TaskProcessor(str(task_id), db_session).process()

    db_session.expire_all()
    status = (await db_session.execute(select(Task.status).where(Task.id == task_id))).scalar_one()
    assert status == "pending"

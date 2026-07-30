"""«Перезапустить» не должен запускать второй прогон поверх живого.

Регресс, видимый прямо в логе прода 29.07.2026: строки `Task still running
elapsed_seconds=2160 task_id=c8b0c97d…` и `Claude API call successful
duration_ms=58395` шли ПАРАМИ — одну задачу считали два обработчика
одновременно, и каждый запрос к ИИ оплачивался дважды. Причина: restart ставил
новую job, не сняв прежнюю, а прежний прогон никак не узнавал, что его сменили.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.models.job import Job
from app.models.task import Task
from app.services import job_queue
from app.services.task_processor import TaskCancelledError, TaskProcessor

pytestmark = pytest.mark.asyncio


async def _clear_jobs(db):
    await db.execute(delete(Job))
    await db.commit()


async def test_supersede_removes_queued_and_running(db_session):
    """Перед новым прогоном снимаются и queued, и running — иначе прогонов два."""
    await _clear_jobs(db_session)
    await job_queue.enqueue(db_session, "task.process", {"task_id": "T-9"}, owner_id=1)
    claimed = await job_queue.claim_one(db_session, "w1")
    assert claimed is not None
    await job_queue.enqueue(db_session, "task.process", {"task_id": "T-9"}, owner_id=1)

    n = await job_queue.supersede_jobs_for_task(db_session, "T-9")

    assert n == 2
    db_session.expire_all()
    statuses = (
        (await db_session.execute(select(Job.status))).scalars().all()
    )
    assert set(statuses) == {"superseded"}
    # Снятую job worker не возьмёт.
    assert await job_queue.claim_one(db_session, "w2") is None


async def test_supersede_spares_other_tasks(db_session):
    """Чужие job рестарт не трогает."""
    await _clear_jobs(db_session)
    await job_queue.enqueue(db_session, "task.process", {"task_id": "T-9"}, owner_id=1)
    other = await job_queue.enqueue(db_session, "task.process", {"task_id": "T-8"}, owner_id=1)
    other_id = other.id

    await job_queue.supersede_jobs_for_task(db_session, "T-9")

    db_session.expire_all()
    status = (
        await db_session.execute(select(Job.status).where(Job.id == other_id))
    ).scalar_one()
    assert status == "queued"


async def _make_task(db, task_id: str, status: str = "processing") -> str:
    task = Task(
        id=task_id,
        task_type="LIST_FROM_GRAND",
        status=status,
        owner_id=1,
        user_role="admin",
    )
    db.add(task)
    await db.commit()
    return task_id


async def test_superseded_run_stops_at_checkpoint(db_session):
    """Прогон, чью job сняли рестартом, выходит на ближайшей проверке отмены.

    Порядок как в `POST /tasks/{id}/restart`: снять прежние job, затем поставить
    новую. Именно новая job и означает «задачу считает уже не ты».
    """
    await _clear_jobs(db_session)
    task_id = await _make_task(db_session, "d0000000-0000-0000-0000-000000000001")
    await job_queue.enqueue(db_session, "task.process", {"task_id": task_id}, owner_id=1)
    claimed = await job_queue.claim_one(db_session, "w1")
    job_id = claimed.id
    await job_queue.supersede_jobs_for_task(db_session, task_id)
    await job_queue.enqueue(db_session, "task.process", {"task_id": task_id}, owner_id=1)

    processor = TaskProcessor(task_id, db_session, job_id=job_id)
    with pytest.raises(TaskCancelledError):
        await processor._check_cancelled()


async def test_live_run_continues(db_session):
    """Пока своя job running — прогон продолжается (ложных остановок нет)."""
    await _clear_jobs(db_session)
    task_id = await _make_task(db_session, "d0000000-0000-0000-0000-000000000002")
    await job_queue.enqueue(db_session, "task.process", {"task_id": task_id}, owner_id=1)
    claimed = await job_queue.claim_one(db_session, "w1")

    processor = TaskProcessor(task_id, db_session, job_id=claimed.id)
    await processor._check_cancelled()  # не должно бросить


async def test_reclaimed_run_stops_zombie(db_session):
    """Ту же job выдали заново (деплой или reclaim) — прежний прогон выходит.

    Деплой возвращает недоигранную job в очередь, reclaim делает то же через 15
    минут без сигнала. Если прежний процесс всё-таки жив, он обязан заметить, что
    задачу считает уже другой: иначе два прогона и двойная оплата запросов к ИИ.
    Признак — номер попытки: каждый захват его увеличивает, heartbeat не трогает.
    """
    await _clear_jobs(db_session)
    task_id = await _make_task(db_session, "d0000000-0000-0000-0000-000000000006")
    await job_queue.enqueue(db_session, "task.process", {"task_id": task_id}, owner_id=1)
    first = await job_queue.claim_one(db_session, "w1")
    job_id, first_attempt = first.id, first.attempts

    # Деплой: job вернулась в очередь и её забрал новый процесс.
    await db_session.execute(
        Job.__table__.update()
        .where(Job.id == job_id)
        .values(status="queued", claimed_by=None, claimed_at=None)
    )
    await db_session.commit()
    second = await job_queue.claim_one(db_session, "w2")
    assert second.attempts > first_attempt

    zombie = TaskProcessor(task_id, db_session, job_id=job_id, job_attempt=first_attempt)
    with pytest.raises(TaskCancelledError):
        await zombie._check_cancelled()

    # А текущий прогон продолжается.
    current = TaskProcessor(task_id, db_session, job_id=job_id, job_attempt=second.attempts)
    await current._check_cancelled()


async def test_lone_run_finishes_even_if_job_marked(db_session):
    """Запись пометили, но другого прогона нет — доводим до конца.

    30.07.2026 автовозврат пометил задачу ошибкой (исчерпаны попытки), пока живой
    обработчик спокойно доводил смету до конца. Остановить его означало бы
    выбросить уже ОПЛАЧЕННУЮ работу — смета в итоге получилась, и правильно.
    """
    await _clear_jobs(db_session)
    task_id = await _make_task(db_session, "d0000000-0000-0000-0000-000000000007")
    await job_queue.enqueue(db_session, "task.process", {"task_id": task_id}, owner_id=1)
    claimed = await job_queue.claim_one(db_session, "w1")
    job_id, attempt = claimed.id, claimed.attempts
    await db_session.execute(
        Job.__table__.update().where(Job.id == job_id).values(status="failed")
    )
    await db_session.commit()

    processor = TaskProcessor(task_id, db_session, job_id=job_id, job_attempt=attempt)
    await processor._check_cancelled()  # не бросает — сменщика нет


async def test_lone_run_stops_when_new_job_exists(db_session):
    """Запись пометили И появилась новая job задачи — выходим, считает она."""
    await _clear_jobs(db_session)
    task_id = await _make_task(db_session, "d0000000-0000-0000-0000-000000000008")
    await job_queue.enqueue(db_session, "task.process", {"task_id": task_id}, owner_id=1)
    claimed = await job_queue.claim_one(db_session, "w1")
    job_id, attempt = claimed.id, claimed.attempts
    await db_session.execute(
        Job.__table__.update().where(Job.id == job_id).values(status="superseded")
    )
    await db_session.commit()
    await job_queue.enqueue(db_session, "task.process", {"task_id": task_id}, owner_id=1)

    processor = TaskProcessor(task_id, db_session, job_id=job_id, job_attempt=attempt)
    with pytest.raises(TaskCancelledError):
        await processor._check_cancelled()


async def test_run_without_job_id_is_not_stopped(db_session):
    """Прогон без job (прямой вызов из роутера) не должен падать на проверке."""
    task_id = await _make_task(db_session, "d0000000-0000-0000-0000-000000000003")
    processor = TaskProcessor(task_id, db_session, job_id=None)
    await processor._check_cancelled()


async def test_restart_keeps_created_at_and_resets_run(async_client, db_session, admin_token):
    """created_at — время создания задачи, его рестарт не переписывает.

    Сброс врал про возраст (задача, висевшая часами, показывала «1 мин»), портил
    колонку «В очереди» и историю длительностей для прогноза. Длительность прогона
    считается от started_at — вот его и сбрасываем.
    """
    old_created = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)
    task = Task(
        id="d0000000-0000-0000-0000-000000000004",
        task_type="LIST_FROM_GRAND",
        status="processing",
        owner_id=1,
        user_role="admin",
        created_at=old_created,
        started_at=datetime(2026, 7, 29, 10, 5, tzinfo=timezone.utc),
        finished_at=datetime(2026, 7, 29, 11, 0, tzinfo=timezone.utc),
    )
    db_session.add(task)
    await db_session.commit()
    task_id = str(task.id)

    r = await async_client.post(
        f"/tasks/{task_id}/restart", headers={"Authorization": admin_token}
    )
    assert r.status_code == 200

    db_session.expire_all()
    row = (
        await db_session.execute(
            select(Task.created_at, Task.started_at, Task.finished_at, Task.status).where(
                Task.id == task_id
            )
        )
    ).first()
    created_at, started_at, finished_at, status = row
    if created_at.tzinfo is None:  # SQLite отдаёт naive
        created_at = created_at.replace(tzinfo=timezone.utc)
    assert created_at == old_created
    assert started_at is None
    assert finished_at is None
    assert status == "pending"


async def test_restart_supersedes_old_job(async_client, db_session, admin_token):
    """После рестарта в очереди ровно один живой прогон, а не два."""
    await _clear_jobs(db_session)
    task = Task(
        id="d0000000-0000-0000-0000-000000000005",
        task_type="LIST_FROM_GRAND",
        status="processing",
        owner_id=1,
        user_role="admin",
    )
    db_session.add(task)
    await db_session.commit()
    task_id = str(task.id)
    await job_queue.enqueue(db_session, "task.process", {"task_id": task_id}, owner_id=1)
    await job_queue.claim_one(db_session, "w1")

    r = await async_client.post(
        f"/tasks/{task_id}/restart", headers={"Authorization": admin_token}
    )
    assert r.status_code == 200

    db_session.expire_all()
    alive = (
        (
            await db_session.execute(
                select(Job.status).where(Job.status.in_(("queued", "running")))
            )
        )
        .scalars()
        .all()
    )
    assert alive == ["queued"]

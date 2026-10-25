"""Признак жизни обработчика в карточке задачи.

Пользователь смотрит на «Обработка» и не может отличить работающую задачу от
мёртвой: heartbeat воркера писался только в лог сервера
(`TaskProcessor._heartbeat`), а наружу не отдавался ничего.

Настоящий признак жизни процесса уже ведёт durable-очередь: `jobs.claimed_at`
продлевается `job_queue.heartbeat` пока job исполняется. Отдаём его возраст в
`/tasks/{id}/status` — новая таблица и миграция не нужны.

JSON-предикаты диалектозависимы (JSONB в проде, JSON в SQLite тестов), поэтому
поиск job по `payload.task_id` идёт на стороне Python — тот же приём, что в
`sweep_orphaned_tasks` и `batch_poller`.

План: plans/2026-07-29-diagnostika-v-admin-panel.md, Фаза 5.
"""
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import delete

from app.models.job import Job
from app.models.task import Task
from app.services import job_queue

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _clean_db(db_session):
    await db_session.execute(delete(Job))
    await db_session.execute(delete(Task))
    await db_session.commit()
    yield
    await db_session.execute(delete(Job))
    await db_session.execute(delete(Task))
    await db_session.commit()


async def _task(db, status="processing") -> Task:
    t = Task(user_role="user", task_type="LIST_FROM_GRAND", status=status, input_files=[])
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def _job(db, task_id, *, status="running", claimed_min_ago=None) -> Job:
    claimed_at = (
        datetime.now(timezone.utc) - timedelta(minutes=claimed_min_ago)
        if claimed_min_ago is not None
        else None
    )
    j = Job(
        kind="task.process",
        payload={"task_id": str(task_id)},
        status=status,
        claimed_at=claimed_at,
    )
    db.add(j)
    await db.commit()
    await db.refresh(j)
    return j


# ---------------------------------------------------------------------------
# job_queue.heartbeat — сигнал продлевается
# ---------------------------------------------------------------------------

async def test_heartbeat_refresh_resets_age(db_session):
    """После heartbeat возраст сигнала сбрасывается почти в ноль."""
    t = await _task(db_session)
    j = await _job(db_session, t.id, status="running", claimed_min_ago=30)

    await job_queue.heartbeat(db_session, j.id)

    age = await job_queue.live_heartbeat_age_s(db_session, str(t.id))
    assert age is not None and age < 5


# ---------------------------------------------------------------------------
# /tasks/{id}/status — поле отдаётся наружу
# ---------------------------------------------------------------------------

async def test_status_endpoint_exposes_heartbeat_age(async_client, db_session, admin_token):
    t = await _task(db_session)
    await _job(db_session, t.id, status="running", claimed_min_ago=3)

    resp = await async_client.get(
        f"/tasks/{t.id}/status", headers={"Authorization": admin_token}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "worker_heartbeat_age_s" in body
    assert body["worker_heartbeat_age_s"] is not None
    assert 170 <= body["worker_heartbeat_age_s"] <= 195


@pytest.mark.parametrize(
    "scenario", ["no_job", "other_task_job", "queued_job", "finished_job"]
)
async def test_status_endpoint_null_without_live_job(
    async_client, db_session, admin_token, scenario
):
    """Нет живого сигнала обработчика ЭТОЙ задачи — null, а не возраст.

    - job нет вовсе;
    - running-job чужой задачи — не признак жизни этой;
    - queued-job ещё не захвачена: claimed_at пуст, сигнала нет;
    - завершённая job — задачу уже никто не обрабатывает.
    """
    t = await _task(db_session, status="pending" if scenario == "queued_job" else "processing")
    if scenario == "other_task_job":
        other = await _task(db_session)
        await _job(db_session, other.id, status="running", claimed_min_ago=1)
    elif scenario == "queued_job":
        await _job(db_session, t.id, status="queued", claimed_min_ago=None)
    elif scenario == "finished_job":
        await _job(db_session, t.id, status="done", claimed_min_ago=1)

    resp = await async_client.get(
        f"/tasks/{t.id}/status", headers={"Authorization": admin_token}
    )
    assert resp.status_code == 200
    assert resp.json()["worker_heartbeat_age_s"] is None

"""Смерть обработчика: job возвращаются в очередь за минуты, а не за 15 минут.

30.07.2026: три возобновлённые задачи замолчали одновременно и «висели вечно».
Причина — контейнер обработчика умирал (OOM-kill при трёх задачах разом), а его
running-job мог вернуть только reclaim по визибилити-таймауту, то есть через 15
минут. Обработчик в контейнере один, поэтому job, помеченная НАШИМ хостом и ЧУЖИМ
pid, — заведомо брошенная: ждать её нечего.

План: plans/2026-07-30-parallelnaya-obrabotka-umiraet.md, Фаза 2.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.models.job import Job
from app.services import job_queue

pytestmark = pytest.mark.asyncio


async def _clear(db):
    await db.execute(delete(Job))
    await db.commit()


async def _running_job(db, claimed_by: str, age_s: float, task_id: str = "t1") -> Job:
    job = await job_queue.enqueue(db, "task.process", {"task_id": task_id})
    job.status = "running"
    job.claimed_by = claimed_by
    job.claimed_at = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    job.attempts = 1
    await db.commit()
    return job


async def test_requeues_job_of_dead_process_on_same_host(db_session):
    """Тот же хост, другой pid, молчит дольше порога → назад в очередь сразу."""
    await _clear(db_session)
    job = await _running_job(db_session, "box-1:100", age_s=200)

    n = await job_queue.reclaim_crashed_worker_jobs(db_session, "box-1:200", 90)

    assert n == 1
    fresh = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert fresh.status == "queued"
    assert fresh.claimed_by is None
    assert fresh.claimed_at is None
    # Смерть процесса — сбой обработки: попытка списывается. Иначе бесконечный
    # OOM-цикл крутился бы вечно вместо честного `failed` с внятным текстом.
    assert fresh.attempts == 1


async def test_own_job_untouched(db_session):
    """Свою же job (тот же pid) не отбираем — её ведёт живой процесс."""
    await _clear(db_session)
    job = await _running_job(db_session, "box-1:200", age_s=999)

    n = await job_queue.reclaim_crashed_worker_jobs(db_session, "box-1:200", 90)

    assert n == 0
    fresh = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert fresh.status == "running"


async def test_fresh_job_untouched(db_session):
    """Heartbeat свежий — процесс жив. Так страхуемся от платформы, выдающей
    двум живым контейнерам одинаковый hostname."""
    await _clear(db_session)
    job = await _running_job(db_session, "box-1:100", age_s=10)

    n = await job_queue.reclaim_crashed_worker_jobs(db_session, "box-1:200", 90)

    assert n == 0
    fresh = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert fresh.status == "running"


async def test_other_host_untouched(db_session):
    """Чужой хост — чужое дело: там свой обработчик и свой reclaim."""
    await _clear(db_session)
    job = await _running_job(db_session, "box-2:100", age_s=999)

    n = await job_queue.reclaim_crashed_worker_jobs(db_session, "box-1:200", 90)

    assert n == 0
    fresh = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert fresh.status == "running"


async def test_similar_host_prefix_untouched(db_session):
    """`box-1` и `box-10` — разные хосты: сравнение идёт по префиксу с двоеточием."""
    await _clear(db_session)
    job = await _running_job(db_session, "box-10:100", age_s=999)

    n = await job_queue.reclaim_crashed_worker_jobs(db_session, "box-1:200", 90)

    assert n == 0
    fresh = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert fresh.status == "running"


async def test_queued_and_done_untouched(db_session):
    """Трогаем только running: очередь и завершённые не наше дело."""
    await _clear(db_session)
    queued = await job_queue.enqueue(db_session, "task.process", {"task_id": "q"})
    done = await _running_job(db_session, "box-1:100", age_s=999, task_id="d")
    done.status = "done"
    await db_session.commit()

    n = await job_queue.reclaim_crashed_worker_jobs(db_session, "box-1:200", 90)

    assert n == 0
    assert (
        await db_session.execute(select(Job.status).where(Job.id == queued.id))
    ).scalar_one() == "queued"
    assert (
        await db_session.execute(select(Job.status).where(Job.id == done.id))
    ).scalar_one() == "done"


async def test_empty_worker_id_is_noop(db_session):
    """Без hostname сравнивать нечего — молча ничего не делаем."""
    await _clear(db_session)
    await _running_job(db_session, "box-1:100", age_s=999)

    assert await job_queue.reclaim_crashed_worker_jobs(db_session, "", 90) == 0
    assert await job_queue.reclaim_crashed_worker_jobs(db_session, ":200", 90) == 0


# ---------------------------------------------------------------------------
# Старт обработчика: подобрать брошенное и записать факт старта
# ---------------------------------------------------------------------------

async def test_announce_start_is_visible_in_admin(
    async_client, admin_token, db_session, app_sessions, monkeypatch
):
    """При старте обработчик забирает брошенные job и оставляет след о себе.

    След нужен, потому что при OOM-kill больше никаких следов нет: жалоба на
    память не пишется, лог контейнера пользователю недоступен. Проверяем весь
    путь: старт → строка в БД → блок «Диагностика» в админке.
    """
    from app import worker
    from app.models.system_event import SystemEvent
    from app.utils.memory import MemorySnapshot

    await _clear(db_session)
    await db_session.execute(delete(SystemEvent))
    await db_session.commit()

    monkeypatch.setattr(worker, "WORKER_ID", "box-1:999")
    # Память контейнера на момент старта (внешний мир: cgroup).
    monkeypatch.setattr(
        worker, "memory_snapshot",
        lambda: MemorySnapshot(rss_mb=780.0, usage_mb=800.0, limit_mb=2048.0, limit_source="cgroup"),
    )
    await _running_job(db_session, "box-1:100", age_s=200)  # job умершего предшественника
    try:
        assert await worker._announce_start(slots=2) == 1

        body = (
            await async_client.get("/admin/queue-health", headers={"Authorization": admin_token})
        ).json()
        info = body["worker_restarts"]
        assert info["starts_1h"] == 1
        assert info["slots"] == 2
        assert info["requeued"] == 1
        assert info["limit_mb"] == 2048.0
        assert info["rss_mb"] == 780.0
        # Брошенная job снова в очереди, а не «в работе» у мёртвого процесса.
        assert body["counts"]["queued"] == 1
        assert body["counts"]["running"] == 0
    finally:
        await _clear(db_session)
        await db_session.execute(delete(SystemEvent))
        await db_session.commit()


async def test_announce_start_survives_db_failure(monkeypatch):
    """БД не готова (первый деплой) — обработчик всё равно поднимается."""
    from app import worker

    class Boom:
        def __call__(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(worker, "AsyncSessionLocal", Boom())

    assert await worker._announce_start(slots=1) == 0

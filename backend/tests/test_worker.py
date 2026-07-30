"""Тесты worker-процесса: диспетчер kind→handler, complete/requeue/fail."""
import asyncio
import pytest
from sqlalchemy import select, delete, update

from app.models.job import Job
from app.services import job_queue
from app import worker

pytestmark = pytest.mark.asyncio


async def _clear(db):
    await db.execute(delete(Job))
    await db.commit()


async def _status(db, job_id: int) -> str:
    db.expire_all()
    row = (await db.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
    return row


async def test_run_job_completes(db_session, monkeypatch):
    from tests.conftest import TestSessionLocal
    # worker открывает свои сессии — направляем на тестовый SQLite (StaticPool, та же БД).
    monkeypatch.setattr(worker, "AsyncSessionLocal", TestSessionLocal)

    seen = {}
    async def handler(payload, db):
        seen["payload"] = payload
    monkeypatch.setitem(worker.HANDLERS, "test.ok", handler)

    await _clear(db_session)
    job = await job_queue.enqueue(db_session, "test.ok", {"x": 1}, owner_id=1)
    job_id = job.id
    claimed = await job_queue.claim_one(db_session, "w1")
    await worker.run_job(claimed)

    assert await _status(db_session, job_id) == "done"
    # payload обработчика = payload job + `_job_id` текущего прогона: по нему
    # обработчик понимает, что его сменил перезапуск (см. test_restart_no_double_run).
    assert seen["payload"] == {"x": 1, "_job_id": job_id}


async def test_run_job_requeues_then_fails(db_session, monkeypatch):
    from tests.conftest import TestSessionLocal
    monkeypatch.setattr(worker, "AsyncSessionLocal", TestSessionLocal)

    async def boom(payload, db):
        raise RuntimeError("boom")
    monkeypatch.setitem(worker.HANDLERS, "test.boom", boom)

    await _clear(db_session)
    job = await job_queue.enqueue(db_session, "test.boom", {}, owner_id=1)
    job_id = job.id

    # Первый заход: attempts=1 (<3) → возврат в очередь.
    claimed = await job_queue.claim_one(db_session, "w1")
    await worker.run_job(claimed)
    assert await _status(db_session, job_id) == "queued"

    # Доводим attempts до порога и повторяем → терминальный fail.
    await db_session.execute(
        update(Job).where(Job.id == job_id).values(attempts=3, status="running", claimed_by="w1")
    )
    await db_session.commit()
    reclaimed = (await db_session.execute(select(Job).where(Job.id == job_id))).scalar_one()
    await worker.run_job(reclaimed)
    assert await _status(db_session, job_id) == "failed"


async def test_heartbeat_survives_db_error(monkeypatch):
    """P0-B: транзиентная ошибка heartbeat не убивает цикл — он продолжает биться.

    Иначе один сбой БД оставил бы живую длинную job без heartbeat → её ошибочно
    реклеймили бы в параллельный прогон.
    """
    calls = {"n": 0}

    async def flaky_heartbeat(db, job_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db blip")  # первый вызов падает

    class _DummyDB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: _DummyDB())
    monkeypatch.setattr(worker.job_queue, "heartbeat", flaky_heartbeat)

    hb = asyncio.create_task(worker._heartbeat_loop(job_id=1, interval=0.005))
    await asyncio.sleep(0.05)  # ~10 интервалов
    hb.cancel()
    await asyncio.gather(hb, return_exceptions=True)

    # Пережил ошибку на 1-м вызове и продолжил (иначе застрял бы на n==1).
    assert calls["n"] >= 3


async def test_run_job_unknown_kind_fails(db_session, monkeypatch):
    from tests.conftest import TestSessionLocal
    monkeypatch.setattr(worker, "AsyncSessionLocal", TestSessionLocal)

    await _clear(db_session)
    job = await job_queue.enqueue(db_session, "does.not.exist", {}, owner_id=1)
    job_id = job.id
    await db_session.execute(update(Job).where(Job.id == job_id).values(attempts=3, status="running"))
    await db_session.commit()
    claimed = (await db_session.execute(select(Job).where(Job.id == job_id))).scalar_one()
    await worker.run_job(claimed)
    assert await _status(db_session, job_id) == "failed"

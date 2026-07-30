"""Одну задачу этот процесс не считает дважды — иначе петля из прогонов.

30.07.2026, вторая часть разбора: в логе ОДНОЙ задачи оказались три записи
«Начало обработки задачи...» и два разных набора чанков, отправленных в ИИ. То
есть задачу считали несколько прогонов сразу: под нагрузкой heartbeat опаздывал,
`reclaim_stale` принимал живой прогон за мёртвый и выдавал второй — процессор
загружался сильнее, опоздание росло, появлялся третий. Web на той же машине
переставал отвечать, страница задачи не загружалась.

Обработчик в контейнере один, поэтому «эта задача уже считается здесь» —
достоверный признак дубля.

План: plans/2026-07-30-parallelnaya-obrabotka-umiraet.md, Фаза 7.
"""
import asyncio

import pytest
from sqlalchemy import delete, select

from app import worker
from app.config import settings
from app.models.job import Job
from app.services import job_queue

pytestmark = pytest.mark.asyncio


def _job(job_id: int, task_id: str) -> Job:
    return Job(
        id=job_id, kind="task.process", payload={"task_id": task_id},
        status="running", attempts=1,
    )


async def test_duplicate_detected_for_running_task(monkeypatch):
    monkeypatch.setattr(worker, "_inflight_task_ids", {5: "task-A"})

    assert worker._duplicate_task_id(_job(9, "task-A")) == "task-A"


async def test_other_task_is_not_duplicate(monkeypatch):
    monkeypatch.setattr(worker, "_inflight_task_ids", {5: "task-A"})

    assert worker._duplicate_task_id(_job(9, "task-B")) is None


async def test_job_without_task_id_is_not_duplicate(monkeypatch):
    """Не все job — про задачи (retrain, version.*): им дубль-проверка не нужна."""
    monkeypatch.setattr(worker, "_inflight_task_ids", {5: "task-A"})

    assert worker._duplicate_task_id(Job(id=9, kind="retrain", payload={"job_id": 1})) is None


async def test_drop_duplicate_job_marks_superseded(db_session):
    """Снятый дубль не должен вернуться в очередь и не должен ронять задачу."""
    await db_session.execute(delete(Job))
    await db_session.commit()
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": "task-A"})
    job.status = "running"
    await db_session.commit()

    assert await job_queue.drop_duplicate_job(db_session, job.id, "task-A") is True

    fresh = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert fresh.status == "superseded"
    assert "дубль" in (fresh.last_error or "")


async def test_drop_duplicate_ignores_not_running(db_session):
    """Guard по статусу: успевшую завершиться job не портим."""
    await db_session.execute(delete(Job))
    await db_session.commit()
    job = await job_queue.enqueue(db_session, "task.process", {"task_id": "task-A"})

    assert await job_queue.drop_duplicate_job(db_session, job.id, "task-A") is False
    fresh = (await db_session.execute(select(Job).where(Job.id == job.id))).scalar_one()
    assert fresh.status == "queued"


async def test_poll_loop_drops_duplicate_and_does_not_run_it(monkeypatch):
    """Главный сценарий: реклейм выдал вторую job живой задачи — прогона не будет."""
    monkeypatch.setattr(worker, "_inflight_task_ids", {1: "task-A"})
    monkeypatch.setattr(worker, "_inflight_job_ids", {1})
    monkeypatch.setattr(worker, "_inflight_started_at", {1: 0.0})
    monkeypatch.setattr(worker, "_memory_brake_engaged", lambda: False)
    monkeypatch.setattr(worker, "_claim_stagger_blocked", lambda: False)
    monkeypatch.setattr(settings, "JOB_POLL_INTERVAL_S", 0.01)

    runs = []
    dropped = []
    handed = {"n": 0}

    async def fake_claim(db, worker_id):
        handed["n"] += 1
        if handed["n"] > 1:
            return None
        return _job(2, "task-A")

    async def fake_drop(db, job_id, task_id):
        dropped.append((job_id, task_id))
        return True

    async def fake_run(j):  # pragma: no cover — не должен вызваться
        runs.append(j.id)

    monkeypatch.setattr(worker.job_queue, "claim_one", fake_claim)
    monkeypatch.setattr(worker.job_queue, "drop_duplicate_job", fake_drop)
    monkeypatch.setattr(worker, "run_job", fake_run)

    shutdown = asyncio.Event()
    monkeypatch.setattr(worker, "_shutdown", shutdown)

    sem = asyncio.Semaphore(2)
    loop_task = asyncio.create_task(worker._poll_loop(sem, set()))
    await asyncio.sleep(0.05)
    shutdown.set()
    await asyncio.wait_for(loop_task, timeout=2)

    assert dropped == [(2, "task-A")]
    assert runs == [], "дубль всё равно ушёл в обработку"
    assert sem._value == 2  # слот возвращён


async def test_inflight_task_ids_cleaned_after_run(monkeypatch):
    """После задачи её id уходит из карты — иначе повторный запуск станет невозможен."""
    monkeypatch.setattr(worker, "_inflight_task_ids", {})
    monkeypatch.setattr(worker, "_inflight_job_ids", set())
    monkeypatch.setattr(worker, "_inflight_started_at", {})
    monkeypatch.setattr(worker, "_memory_brake_engaged", lambda: False)
    monkeypatch.setattr(worker, "_claim_stagger_blocked", lambda: False)
    monkeypatch.setattr(settings, "JOB_POLL_INTERVAL_S", 0.01)

    seen = {}
    handed = {"n": 0}

    async def fake_claim(db, worker_id):
        handed["n"] += 1
        return _job(3, "task-Z") if handed["n"] == 1 else None

    async def fake_run(j):
        seen["during"] = dict(worker._inflight_task_ids)

    monkeypatch.setattr(worker.job_queue, "claim_one", fake_claim)
    monkeypatch.setattr(worker, "run_job", fake_run)

    shutdown = asyncio.Event()
    monkeypatch.setattr(worker, "_shutdown", shutdown)

    inflight: set = set()
    loop_task = asyncio.create_task(worker._poll_loop(asyncio.Semaphore(2), inflight))
    await asyncio.sleep(0.05)
    shutdown.set()
    await asyncio.wait_for(loop_task, timeout=2)
    await asyncio.gather(*list(inflight), return_exceptions=True)

    assert seen["during"] == {3: "task-Z"}
    assert worker._inflight_task_ids == {}


# ---------------------------------------------------------------------------
# Процессор: одно ядро остаётся интерфейсу
# ---------------------------------------------------------------------------

async def test_cpu_cap_leaves_a_core_for_web(monkeypatch):
    monkeypatch.setattr(worker.os, "cpu_count", lambda: 4)
    assert worker._cpu_slots_cap() == 3


async def test_cpu_cap_never_below_one(monkeypatch):
    """Одно ядро — по-прежнему один слот, иначе очередь не движется вовсе."""
    monkeypatch.setattr(worker.os, "cpu_count", lambda: 1)
    assert worker._cpu_slots_cap() == 1


async def test_cpu_cap_unknown_cores(monkeypatch):
    monkeypatch.setattr(worker.os, "cpu_count", lambda: None)
    assert worker._cpu_slots_cap() is None


async def test_slots_limited_by_cpu(monkeypatch):
    """Настроено 4, ядер 2 → берём 1: иначе интерфейс перестаёт отвечать."""
    from app.utils.memory import MemorySnapshot

    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 4)
    monkeypatch.setattr(worker.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(
        worker, "memory_snapshot",
        lambda: MemorySnapshot(rss_mb=200.0, usage_mb=None, limit_mb=None),
    )

    assert worker._effective_slots() == 1


async def test_embedding_threads_leave_a_core():
    """Эмбеддинги не забирают все ядра: ONNX по умолчанию берёт именно все."""
    from app.services import embedding_service

    threads = embedding_service._embedding_threads()
    assert threads >= 1
    cores = embedding_service.os.cpu_count() or 2
    assert threads <= max(1, cores - 1) or threads == settings.EMBEDDING_THREADS


async def test_embedding_threads_explicit_setting(monkeypatch):
    from app.services import embedding_service

    monkeypatch.setattr(settings, "EMBEDDING_THREADS", 3)
    assert embedding_service._embedding_threads() == 3


async def test_fastembed_without_threads_param_still_loads():
    """Старая версия fastembed не знает `threads` — поиск цен важнее ограничения."""
    from app.services import embedding_service

    calls = []

    class OldTextEmbedding:
        def __init__(self, model_path, **kwargs):
            if kwargs:
                raise TypeError("unexpected keyword argument")
            calls.append(model_path)

    model = embedding_service._make_fastembed(OldTextEmbedding, "some-model")
    assert isinstance(model, OldTextEmbedding)
    assert calls == ["some-model"]

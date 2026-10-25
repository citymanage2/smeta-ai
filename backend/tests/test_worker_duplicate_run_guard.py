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


async def test_poll_loop_drops_duplicate_and_does_not_run_it(worker_loop):
    """Главный сценарий: реклейм выдал вторую job живой задачи — прогона не будет."""
    held = worker_loop.hold("task.process")
    first = await worker_loop.enqueue("task.process", {"task_id": "task-A"})

    async with worker_loop.running(slots=2):
        await held.wait_started(1)
        duplicate = await worker_loop.enqueue("task.process", {"task_id": "task-A"})

        await worker_loop.wait_status(duplicate, "superseded")
        assert len(held.started) == 1, "дубль всё равно ушёл в обработку"
        assert await worker_loop.status(first) == "running"

        held.release()
        await worker_loop.wait_status(first, "done")


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


async def test_embedding_threads_leave_a_core(monkeypatch):
    """Эмбеддинги не забирают все ядра: ONNX по умолчанию берёт именно все."""
    from app.services import embedding_service

    monkeypatch.setattr(settings, "EMBEDDING_THREADS", 0)
    monkeypatch.setattr(embedding_service.os, "cpu_count", lambda: 4)

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

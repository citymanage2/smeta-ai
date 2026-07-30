"""Повторная попытка после сбоя должна быть видна в карточке задачи.

Было: job тихо возвращалась в очередь, задача оставалась в «Обработке» с прежним
шагом, а текст ошибки уходил только в лог контейнера — пользователю недоступный.
Внешне это неотличимо от зависания, и именно так выглядели «повисшие» задачи
30.07.2026.

План: plans/2026-07-30-parallelnaya-obrabotka-umiraet.md, Фаза 6.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.task import Task
from app.services import job_queue

pytestmark = pytest.mark.asyncio


async def _task(db, status: str = "processing") -> Task:
    task = Task(
        id=str(uuid.uuid4()),
        task_type="LIST_FROM_GRAND",
        user_role="user",
        status=status,
        progress_message="Анализ файла гранд-сметы...",
        progress_log=["Начало обработки задачи...", "Анализ файла гранд-сметы..."],
    )
    db.add(task)
    await db.commit()
    return task


async def test_retry_message_lands_in_task(db_session):
    task = await _task(db_session)

    assert await job_queue.note_retry_on_task(
        db_session, task.id, 1, 3, "S3 get failed: connection reset"
    ) is True
    await db_session.commit()

    fresh = (await db_session.execute(select(Task).where(Task.id == task.id))).scalar_one()
    assert "попытка 1 из 3" in fresh.progress_message
    assert "connection reset" in fresh.progress_message
    # И в журнале шагов: пользователь видит историю, а не только последнюю строку.
    assert any("попытка 1 из 3" in line for line in fresh.progress_log)


async def test_finished_task_untouched(db_session):
    """Guard по статусу: в завершённую задачу сообщение о сбое не пишем."""
    task = await _task(db_session, status="completed")

    assert await job_queue.note_retry_on_task(db_session, task.id, 2, 3, "boom") is False
    await db_session.commit()

    fresh = (await db_session.execute(select(Task).where(Task.id == task.id))).scalar_one()
    assert fresh.progress_message == "Анализ файла гранд-сметы..."


async def test_missing_task_is_noop(db_session):
    assert await job_queue.note_retry_on_task(db_session, None, 1, 3, "boom") is False
    assert await job_queue.note_retry_on_task(db_session, "нет-такой", 1, 3, "boom") is False


async def test_long_error_is_trimmed(db_session):
    """Длинная трасса не должна распухать карточку и колонку прогресса."""
    task = await _task(db_session)

    await job_queue.note_retry_on_task(db_session, task.id, 1, 3, "x" * 5000)
    await db_session.commit()

    fresh = (await db_session.execute(select(Task).where(Task.id == task.id))).scalar_one()
    assert len(fresh.progress_message) < 400


async def test_worker_reports_retry_on_failure(db_session, monkeypatch):
    """Сквозная проверка: упавший обработчик оставляет след в карточке задачи."""
    from app import worker
    from app.config import settings
    from app.models.job import Job
    from tests.conftest import TestSessionLocal

    monkeypatch.setattr(worker, "AsyncSessionLocal", TestSessionLocal)
    monkeypatch.setattr(settings, "JOB_MAX_ATTEMPTS", 3)
    task = await _task(db_session)

    row = await job_queue.enqueue(db_session, "task.process", {"task_id": task.id})
    row.status = "running"
    row.attempts = 1
    await db_session.commit()
    # `run_job` в проде получает job, прочитанную в отдельной сессии, которая уже
    # закрыта. Повторяем это: отсоединённый объект с теми же полями.
    job = Job(
        id=row.id, kind="task.process", payload={"task_id": task.id},
        status="running", attempts=1,
    )

    async def boom(payload, db):
        raise RuntimeError("прокси не ответил")

    monkeypatch.setitem(worker.HANDLERS, "task.process", boom)
    monkeypatch.setattr(worker, "_report_memory_if_high", lambda *a, **k: _noop())

    await worker.run_job(job)

    # Читаем отдельной сессией: обработчик писал своими, и сессия теста об этих
    # изменениях ничего не знает.
    async with TestSessionLocal() as db:
        job_status = (
            await db.execute(select(Job.status).where(Job.id == job.id))
        ).scalar_one()
        message = (
            await db.execute(select(Task.progress_message).where(Task.id == task.id))
        ).scalar_one()

    assert job_status == "queued"  # попытка ещё есть
    assert "прокси не ответил" in message
    assert "попытка 1 из 3" in message


async def _noop():
    return None

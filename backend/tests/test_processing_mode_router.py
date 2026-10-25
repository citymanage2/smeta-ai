"""
Phase 6 — режим обработки при создании задачи (`POST /tasks`).

Долгий режим (`batch`) есть только у сметы из перечня; у прочих типов и при
непонятном значении задача считается быстро (`fast`). Проверяется то, что
легло в задачу, — по нему воркер выбирает путь расчёта.

План: plans/2026-07-21-estimate-processing-modes.md, Phase 6.
"""
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.models.job import Job
from app.models.task import Task
from app.models.task_input_file import TaskInputFile


@pytest_asyncio.fixture
async def created_removed(db_session):
    """Задача из `POST /tasks` пишется в БД и сразу встаёт в очередь — убираем за собой."""
    before_tasks = set((await db_session.execute(select(Task.id))).scalars().all())
    before_jobs = set((await db_session.execute(select(Job.id))).scalars().all())
    yield
    await db_session.rollback()
    new_tasks = set((await db_session.execute(select(Task.id))).scalars().all()) - before_tasks
    new_jobs = set((await db_session.execute(select(Job.id))).scalars().all()) - before_jobs
    await db_session.execute(delete(Job).where(Job.id.in_(new_jobs)))
    await db_session.execute(delete(TaskInputFile).where(TaskInputFile.task_id.in_(new_tasks)))
    await db_session.execute(delete(Task).where(Task.id.in_(new_tasks)))
    await db_session.commit()


@pytest.mark.parametrize(
    "task_type, requested, stored",
    [
        ("ESTIMATE_FROM_LIST", None, "fast"),      # по умолчанию — быстро
        ("ESTIMATE_FROM_LIST", "batch", "batch"),
        ("ESTIMATE_FROM_LIST", "BATCH", "batch"),  # регистр не важен
        ("ESTIMATE_FROM_LIST", "turbo", "fast"),   # непонятное значение
        ("LIST_FROM_GRAND", "batch", "fast"),      # batch есть только у сметы
    ],
)
async def test_created_task_gets_resolved_processing_mode(
    async_client, user_token, db_session, created_removed,
    task_type, requested, stored,
):
    data = {"task_type": task_type}
    if requested is not None:
        data["processing_mode"] = requested

    response = await async_client.post(
        "/tasks",
        data=data,
        files={"files": ("test.pdf", b"%PDF-1.4 test", "application/pdf")},
        headers={"Authorization": user_token},
    )

    assert response.status_code == 200
    task_id = response.json()["task_id"]
    db_session.expire_all()
    task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
    assert task.processing_mode == stored

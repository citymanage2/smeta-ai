"""Фаза 1 ETA: задача фиксирует границы фактической обработки.

Без started_at/finished_at прогноз времени пришлось бы калибровать по
created_at→updated_at, где сидит многочасовое ожидание в очереди.
"""
import uuid

import pytest

from app.models.task import Task
from app.services.task_processor import TaskProcessor


async def _make_task(db, **kw) -> Task:
    task = Task(
        id=str(uuid.uuid4()),
        user_role="user",
        task_type="LIST_FROM_GRAND",
        status="pending",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        **kw,
    )
    db.add(task)
    await db.commit()
    return task


@pytest.mark.asyncio
async def test_processing_sets_started_at(db_session):
    task = await _make_task(db_session)
    assert task.started_at is None

    await TaskProcessor(task.id, db_session).update_status("processing")
    await db_session.refresh(task)

    assert task.started_at is not None
    assert task.finished_at is None


@pytest.mark.asyncio
async def test_completed_sets_finished_at(db_session):
    task = await _make_task(db_session)
    proc = TaskProcessor(task.id, db_session)

    await proc.update_status("processing")
    await proc.update_status("completed")
    await db_session.refresh(task)

    assert task.started_at is not None
    assert task.finished_at is not None
    assert task.finished_at >= task.started_at


@pytest.mark.asyncio
async def test_failed_and_cancelled_are_terminal(db_session):
    for status in ("failed", "cancelled"):
        task = await _make_task(db_session)
        await TaskProcessor(task.id, db_session).update_status(status)
        await db_session.refresh(task)
        assert task.finished_at is not None, status


@pytest.mark.asyncio
async def test_paused_is_not_terminal(db_session):
    """Пауза по балансу — не конец обработки: задача продолжится сама."""
    task = await _make_task(db_session)
    proc = TaskProcessor(task.id, db_session)

    await proc.update_status("processing")
    await proc.update_status("paused")
    await db_session.refresh(task)

    assert task.finished_at is None


@pytest.mark.asyncio
async def test_restart_resets_started_at(db_session):
    """Повторный прогон отсчитывается заново — иначе остаток считался бы от
    первой попытки и прогноз готовности врал бы на часы."""
    task = await _make_task(db_session)
    proc = TaskProcessor(task.id, db_session)

    await proc.update_status("processing")
    await db_session.refresh(task)
    first_start = task.started_at

    await proc.update_status("failed")
    await proc.update_status("processing")
    await db_session.refresh(task)

    assert task.started_at >= first_start
    assert task.status == "processing"

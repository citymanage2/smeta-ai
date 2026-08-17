"""Падение оптимизации пишет в базу причину, а не `repr` исключения.

Прод 13–14.08.2026: в журнале ошибок стояло «'unit'» — так печатается
`KeyError('unit')`. По такой строке не понять ни рода ошибки, ни что делать.
`task_processor` уже описывал исключение через `describe_exception`, а фоновая
оптимизация — нет, и оставалась единственным местом, откуда голый `repr`
попадал в базу.

План: plans/2026-08-18-ponyatnyy-tekst-oshibki.md, Фаза 3.
"""
import pytest
from sqlalchemy import select

from app.models.task import Task
from app.routers.tasks import _run_optimization_background

pytestmark = pytest.mark.asyncio


def _same_session_factory(session):
    """Фабрика, отдающая одну и ту же тест-сессию (без закрытия/rollback)."""
    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    return lambda: _Ctx()


async def _task(db) -> Task:
    t = Task(
        user_role="user",
        task_type="ESTIMATE_FROM_LIST",
        status="processing",
        input_files=[],
        input_file_data=[],
        chat_history=[],
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def test_optimization_failure_names_the_kind_of_error(db_session):
    task = await _task(db_session)

    # Позиция без row_index роняет разбор до любого обращения к ИИ:
    # str(KeyError('row_index')) — это «'row_index'», и раньше ровно это
    # оказывалось в журнале ошибок.
    await _run_optimization_background(
        task_id=str(task.id),
        items=[{"name": "Кладка стен", "price_incl_vat": 100}],
        prompt="",
        estimate_bytes=b"",
        session_factory=_same_session_factory(db_session),
    )

    refreshed = (
        await db_session.execute(select(Task).where(Task.id == task.id))
    ).scalar_one()
    assert refreshed.status == "failed"
    assert refreshed.error_message == "KeyError: 'row_index'"

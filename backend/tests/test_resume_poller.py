"""
Фаза 4 — планировщик авто-возобновления задач на паузе (paused).

Контракт:
- _has_checkpoint: предикат «есть чекпоинт» (тот же, что у ручного resume-
  эндпоинта); для paused он больше НЕ обязателен — см. Фазу 8.
- resume_paused_tasks берёт ВСЕ paused-задачи и только их, атомарно переводит
  paused→pending и ставит durable-job; уже перехваченную задачу второй раз не
  берёт (гард от двойного запуска).

План: plans/2026-07-21-resume-and-balance-pause.md, Фаза 4.
"""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, select

sys.modules.setdefault("fitz", MagicMock())

import app.services.resume_poller as rp  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.task import Task  # noqa: E402


async def _seed(db, *, status="paused", progress_data=None, task_type="LIST_FROM_GRAND") -> Task:
    t = Task(
        user_role="user",
        task_type=task_type,
        status=status,
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_data=progress_data,
    )
    db.add(t)
    await db.flush()
    await db.refresh(t)
    return t


# ---------------------------------------------------------------------------
# _has_checkpoint — предикат возобновляемости
# ---------------------------------------------------------------------------

def test_has_checkpoint_variants():
    assert rp._has_checkpoint({"chunks_done": 3}) is True
    assert rp._has_checkpoint({"_stage": "pre_excel"}) is True
    assert rp._has_checkpoint({"_stage": "claude_partial"}) is True
    # OCR-чекпоинты (LIST_FROM_GRAND PDF): частичный и полный OCR
    assert rp._has_checkpoint({"ocr_pages_partial": [{"page": 1, "text": "x"}]}) is True
    assert rp._has_checkpoint({"ocr_pages": [{"page": 1, "text": "x"}]}) is True
    # без чекпоинта / незнакомый stage / пусто
    assert rp._has_checkpoint({"_stage": "batch_pending"}) is False
    assert rp._has_checkpoint({}) is False
    assert rp._has_checkpoint(None) is False


# ---------------------------------------------------------------------------
# resume_paused_tasks — захват paused-задач и постановка job
# ---------------------------------------------------------------------------

def _same_session_factory(session):
    """Фабрика, отдающая одну и ту же тест-сессию (без закрытия/rollback)."""
    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    def _factory():
        return _Ctx()

    return _factory


async def _ping_ok() -> dict:
    """Баланс есть. Инъекция вместо реального api_ping — тест не ходит в сеть."""
    return {"ok": True, "is_balance_error": False, "status_code": 200, "error": None}


async def _task_jobs(db) -> list[dict]:
    return (
        await db.execute(select(Job.payload).where(Job.kind == "task.process").order_by(Job.id))
    ).scalars().all()


async def test_resume_takes_every_paused_task_and_only_paused(db_session):
    """Фаза 8: берём ВСЕ paused, включая без чекпоинта (баланс кончился до первого
    чекпоинта — такую задачу надо перезапустить с нуля, иначе она мертва).
    failed с чекпоинтом поллер не трогает: её продолжают кнопкой."""
    await db_session.execute(delete(Job))
    await db_session.commit()
    ok = await _seed(db_session, status="paused", progress_data={"chunks_done": 2})
    no_cp = await _seed(db_session, status="paused", progress_data={})
    failed = await _seed(db_session, status="failed", progress_data={"chunks_done": 1})
    partial = await _seed(db_session, status="paused", progress_data={"_stage": "claude_partial"})
    ids = [ok.id, no_cp.id, failed.id, partial.id]
    try:
        claimed = await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session), pinger=_ping_ok
        )

        assert sorted(claimed) == sorted([ok.id, no_cp.id, partial.id])
        assert sorted(p["task_id"] for p in await _task_jobs(db_session)) == sorted(claimed)
        await db_session.refresh(failed)
        assert failed.status == "failed"
    finally:
        await db_session.execute(delete(Job))
        await db_session.execute(delete(Task).where(Task.id.in_(ids)))
        await db_session.commit()


async def test_overlapping_ticks_take_task_once(db_session):
    """Гард от двойного запуска: пока один тик проверял баланс, задачу уже взял
    другой тик — второй раз её не берут, job в очереди одна.

    Второй тик проходит целиком внутри пробного вызова API первого: первый к
    этому моменту уже выбрал задачу кандидатом, но захват у него не проходит.
    """
    await db_session.execute(delete(Job))
    await db_session.commit()
    t = await _seed(db_session, status="paused", progress_data={"chunks_done": 1})
    task_id = t.id  # неудачный захват делает rollback, и атрибуты строки истекают
    factory = _same_session_factory(db_session)
    second_tick: list[str] = []

    async def ping_while_second_tick_runs() -> dict:
        second_tick.extend(await rp.resume_paused_tasks(session_factory=factory, pinger=_ping_ok))
        return await _ping_ok()

    try:
        first_tick = await rp.resume_paused_tasks(
            session_factory=factory, pinger=ping_while_second_tick_runs
        )

        assert second_tick == [task_id]
        assert first_tick == []
        assert await _task_jobs(db_session) == [{"task_id": task_id}]
        status = (await db_session.execute(select(Task.status).where(Task.id == task_id))).scalar_one()
        assert status == "pending"
    finally:
        await db_session.execute(delete(Job))
        await db_session.execute(delete(Task).where(Task.id == task_id))
        await db_session.commit()


@pytest.mark.parametrize(
    "progress_data",
    [{"chunks_done": 1}, {}],
    ids=["with_checkpoint", "without_checkpoint"],
)
async def test_resume_paused_tasks_enqueues_job(db_session, progress_data):
    """P1: поллер АТОМАРНО ставит durable-job task.process,
    а не запускает обработку напрямую мимо очереди.

    Фаза 8: чекпоинт не обязателен — paused без него (баланс кончился до первого
    чекпоинта) тоже возвращается в очередь, иначе задача мертва."""
    await db_session.execute(delete(Job))
    await db_session.commit()
    resumable = await _seed(db_session, status="paused", progress_data=progress_data)
    try:
        claimed = await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session),
            pinger=_ping_ok,
        )
        assert claimed == [resumable.id]
        await db_session.refresh(resumable)
        assert resumable.status == "pending"

        jobs = (
            await db_session.execute(select(Job).where(Job.kind == "task.process"))
        ).scalars().all()
        assert len(jobs) == 1
        assert jobs[0].payload == {"task_id": resumable.id}
        assert jobs[0].status == "queued"
    finally:
        await db_session.execute(delete(Job))
        await db_session.execute(delete(Task).where(Task.id == resumable.id))
        await db_session.commit()


async def test_resume_paused_tasks_noop_when_none(db_session):
    pinger = AsyncMock()
    claimed = await rp.resume_paused_tasks(
        session_factory=_same_session_factory(db_session),
        pinger=pinger,
    )
    assert claimed == []
    # AC1: нет пауз → пробный вызов API не делается вовсе (тик бесплатен).
    pinger.assert_not_called()

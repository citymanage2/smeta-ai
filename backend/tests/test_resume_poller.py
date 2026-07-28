"""
Фаза 4 — планировщик авто-возобновления задач на паузе (paused).

Контракт:
- _has_checkpoint: предикат «есть чекпоинт» (тот же, что у ручного resume-
  эндпоинта); для paused он больше НЕ обязателен — см. Фазу 8.
- _find_resumable_paused_ids: выбирает все paused-задачи.
- _claim: атомарно paused→pending; повторный захват уже перехваченной задачи
  возвращает False (гард от двойного запуска).
- resume_paused_tasks: захватывает кандидатов и запускает runner для каждого.

План: plans/2026-07-21-resume-and-balance-pause.md, Фаза 4.
"""
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("fitz", MagicMock())

import app.services.resume_poller as rp  # noqa: E402
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
# _find_resumable_paused_ids — все paused (Фаза 8: чекпоинт не обязателен)
# ---------------------------------------------------------------------------

async def test_find_resumable_paused_ids_filters(db_session):
    """Фаза 8: берём ВСЕ paused, включая без чекпоинта (баланс кончился до первого
    чекпоинта — такую задачу надо перезапустить с нуля, иначе она мертва)."""
    ok = await _seed(db_session, status="paused", progress_data={"chunks_done": 2})
    no_cp = await _seed(db_session, status="paused", progress_data={})     # нет чекпоинта
    await _seed(db_session, status="failed", progress_data={"chunks_done": 1})  # не paused
    partial = await _seed(db_session, status="paused", progress_data={"_stage": "claude_partial"})

    ids = await rp._find_resumable_paused_ids(db_session)

    assert ok.id in ids
    assert no_cp.id in ids
    assert partial.id in ids
    assert len(ids) == 3  # failed — исключён


# ---------------------------------------------------------------------------
# _claim — атомарный захват paused→pending, гард от двойного
# ---------------------------------------------------------------------------

async def test_claim_flips_paused_to_pending_once(db_session):
    t = await _seed(db_session, status="paused", progress_data={"chunks_done": 1})

    first = await rp._claim(db_session, t.id)
    assert first is True
    await db_session.refresh(t)
    assert t.status == "pending"
    assert t.error_message is None

    # повторный захват — уже не paused → False (гард от двойного запуска)
    second = await rp._claim(db_session, t.id)
    assert second is False


# ---------------------------------------------------------------------------
# resume_paused_tasks — оркестрация: захват + запуск runner
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


async def test_resume_paused_tasks_claims_and_runs(db_session):
    resumable = await _seed(db_session, status="paused", progress_data={"chunks_done": 1})
    ids_to_cleanup = []

    runner = AsyncMock(return_value=None)
    try:
        claimed = await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session),
            runner=runner,
        )
        ids_to_cleanup = claimed

        assert claimed == [resumable.id]
        await db_session.refresh(resumable)
        assert resumable.status == "pending"

        # runner запущен fire-and-forget — даём циклу прокрутиться.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        runner.assert_awaited_once_with(resumable.id)
    finally:
        # committed-строки чистим (in-memory БД живёт весь session-scope).
        from sqlalchemy import delete
        await db_session.execute(delete(Task).where(Task.id.in_([resumable.id] + ids_to_cleanup)))
        await db_session.commit()


async def test_resume_paused_tasks_enqueues_job(db_session):
    """P1: прод-путь (без инъекции runner) АТОМАРНО ставит durable-job task.process,
    а не запускает обработку напрямую мимо очереди."""
    from sqlalchemy import delete, select
    from app.models.job import Job

    await db_session.execute(delete(Job))
    await db_session.commit()
    resumable = await _seed(db_session, status="paused", progress_data={"chunks_done": 1})
    try:
        claimed = await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session),
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
    runner = AsyncMock()
    claimed = await rp.resume_paused_tasks(
        session_factory=_same_session_factory(db_session),
        runner=runner,
    )
    assert claimed == []
    runner.assert_not_called()

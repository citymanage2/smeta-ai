"""Гейт по пробному вызову API перед возобновлением + событие о пополнении.

Контракт (spec: specs/2026-07-28-balance-restored-notification.md):
- AC1: нет paused-задач → api_ping не вызывается вообще;
- AC2: ping не ok → ни одна задача не тронута, job нет, события нет;
- AC3: ping не ok → у paused обновлён progress_message (время + причина),
       progress_log не растёт;
- AC4/AC5: ping ok → возобновление как раньше + строка system_events;
- AC6: ping ok, но захватывать нечего → события нет.

План: plans/2026-07-28-balance-restored-notification.md, Фаза 2.
"""
import sys
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import delete, select

sys.modules.setdefault("fitz", MagicMock())

import app.services.resume_poller as rp  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.system_event import KIND_BALANCE_RESTORED, SystemEvent  # noqa: E402
from app.models.task import Task  # noqa: E402


def _same_session_factory(session):
    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    return lambda: _Ctx()


async def _seed(db, *, status="paused", progress_data=None, progress_message=None) -> Task:
    t = Task(
        user_role="user",
        task_type="LIST_FROM_GRAND",
        status=status,
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_data=progress_data,
        progress_message=progress_message,
        progress_log=["шаг 1"],
    )
    db.add(t)
    await db.flush()
    await db.refresh(t)
    return t


async def _cleanup(db):
    await db.execute(delete(Job))
    await db.execute(delete(SystemEvent))
    await db.execute(delete(Task))
    await db.commit()


def _ping(ok: bool, *, balance: bool = True, code=400, error="credit balance is too low"):
    async def _call() -> dict:
        return {
            "ok": ok,
            "is_balance_error": (not ok) and balance,
            "status_code": 200 if ok else code,
            "error": None if ok else error,
        }

    return _call


# ---------------------------------------------------------------------------
# AC1 — нет пауз: пробный вызов не делается
# ---------------------------------------------------------------------------

async def test_no_paused_tasks_skips_ping(db_session):
    await _cleanup(db_session)
    pinger = AsyncMock()

    claimed = await rp.resume_paused_tasks(
        session_factory=_same_session_factory(db_session), pinger=pinger
    )

    assert claimed == []
    pinger.assert_not_called()


# ---------------------------------------------------------------------------
# AC2/AC3 — баланс всё ещё пуст: задачи не трогаем, но отмечаем проверку
# ---------------------------------------------------------------------------

async def test_balance_still_empty_leaves_tasks_untouched(db_session):
    await _cleanup(db_session)
    task = await _seed(db_session, progress_data={"chunks_done": 2})
    await db_session.commit()
    try:
        claimed = await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session), pinger=_ping(False)
        )

        assert claimed == []
        await db_session.refresh(task)
        assert task.status == "paused", "слепой перезапуск при пустом балансе запрещён"

        jobs = (await db_session.execute(select(Job))).scalars().all()
        assert jobs == []
        events = (await db_session.execute(select(SystemEvent))).scalars().all()
        assert events == []
    finally:
        await _cleanup(db_session)


async def test_failed_check_marks_progress_message(db_session):
    await _cleanup(db_session)
    task = await _seed(db_session, progress_data={"chunks_done": 2})
    await db_session.commit()
    try:
        await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session), pinger=_ping(False)
        )

        await db_session.refresh(task)
        msg = task.progress_message or ""
        assert "Проверка в" in msg
        assert "баланс всё ещё исчерпан" in msg
        assert "credit balance is too low" in msg
        # AC3: история шагов не засоряется строкой проверки каждые 10 минут.
        assert task.progress_log == ["шаг 1"]
        assert len(msg) <= 500
    finally:
        await _cleanup(db_session)


async def test_non_balance_error_reported_separately(db_session):
    """Ping упал не из-за денег (сеть/401) — текст должен это различать, иначе
    пользователь будет пополнять баланс, который и так полон."""
    await _cleanup(db_session)
    task = await _seed(db_session)
    await db_session.commit()
    try:
        await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session),
            pinger=_ping(False, balance=False, code=401, error="invalid x-api-key"),
        )

        await db_session.refresh(task)
        msg = task.progress_message or ""
        assert "API недоступен (401)" in msg
        assert "баланс всё ещё исчерпан" not in msg
    finally:
        await _cleanup(db_session)


# ---------------------------------------------------------------------------
# AC4/AC5 — баланс восстановлен: возобновляем и пишем событие
# ---------------------------------------------------------------------------

async def test_balance_restored_resumes_and_records_event(db_session):
    await _cleanup(db_session)
    task = await _seed(db_session, progress_data={"chunks_done": 2})
    await db_session.commit()
    try:
        claimed = await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session), pinger=_ping(True)
        )

        assert claimed == [task.id]
        await db_session.refresh(task)
        assert task.status == "pending"

        events = (await db_session.execute(select(SystemEvent))).scalars().all()
        assert len(events) == 1
        assert events[0].kind == KIND_BALANCE_RESTORED
        assert events[0].payload == {"resumed_task_ids": [task.id]}
    finally:
        await _cleanup(db_session)


async def test_batch_task_included_in_event(db_session):
    """Batch-задача возвращается в processing (пачка оплачена) — для пользователя
    это тоже «возобновлена», значит должна попасть в событие."""
    await _cleanup(db_session)
    batch = await _seed(
        db_session, progress_data={"_stage": "batch_pending", "batch_id": "msgbatch_x"}
    )
    await db_session.commit()
    try:
        claimed = await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session), pinger=_ping(True)
        )

        assert claimed == [], "batch-задачу не пересчитываем заново"
        await db_session.refresh(batch)
        assert batch.status == "processing"

        events = (await db_session.execute(select(SystemEvent))).scalars().all()
        assert len(events) == 1
        assert events[0].payload["resumed_task_ids"] == [batch.id]
    finally:
        await _cleanup(db_session)


# ---------------------------------------------------------------------------
# AC6 — захватывать нечего: события нет
# ---------------------------------------------------------------------------

async def test_no_event_when_nothing_claimed(db_session):
    """Параллельный тик уже перехватил задачу: _claim вернёт False → событие о
    пополнении писать не о чем."""
    await _cleanup(db_session)
    task = await _seed(db_session, progress_data={"chunks_done": 1})
    await db_session.commit()

    async def _steal(db, task_id):
        return False

    original = rp._claim_and_enqueue
    rp._claim_and_enqueue = _steal
    try:
        claimed = await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session), pinger=_ping(True)
        )

        assert claimed == []
        events = (await db_session.execute(select(SystemEvent))).scalars().all()
        assert events == []
        await db_session.refresh(task)
        assert task.status == "paused"
    finally:
        rp._claim_and_enqueue = original
        await _cleanup(db_session)

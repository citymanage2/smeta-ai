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
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, select, update

sys.modules.setdefault("fitz", MagicMock())

import app.services.resume_poller as rp  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.system_event import KIND_BALANCE_RESTORED, SystemEvent  # noqa: E402
from app.models.task import Task  # noqa: E402
from tests.conftest import TestSessionLocal  # noqa: E402
from tests.helpers.anthropic_api import api_error, balance_error, claude_message  # noqa: E402


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


LONG_API_TEXT = "Your credit balance is too low. " + "x" * 600


@pytest.mark.parametrize("api_answer, shown", [
    # Денег нет: в карточке — что именно ответил API.
    pytest.param(balance_error(400, "credit balance is too low"),
                 ["credit balance is too low"], id="balance"),
    # Ping упал не из-за денег (ключ): код и текст отличают это от пустого
    # счёта — иначе пользователь пополнял бы баланс, который и так полон.
    pytest.param(api_error(401, "invalid x-api-key"),
                 ["401", "invalid x-api-key"], id="auth"),
    # Длинный ответ API обрезается под размер поля progress_message.
    pytest.param(balance_error(400, LONG_API_TEXT),
                 ["Your credit balance is too low."], id="long-answer"),
])
async def test_failed_check_marks_progress_message(db_session, claude_api, api_answer, shown):
    """Проверка не прошла: у задачи на паузе — время и сырой ответ API, а история
    шагов (`progress_log`) не растёт строкой проверки каждые 10 минут."""
    await _cleanup(db_session)
    task = await _seed(db_session, progress_data={"chunks_done": 2})
    await db_session.commit()
    claude_api(api_answer)
    try:
        await rp.resume_paused_tasks(session_factory=_same_session_factory(db_session))

        await db_session.refresh(task)
        msg = task.progress_message or ""
        for fragment in shown:
            assert fragment in msg
        assert len(msg) <= 500
        assert task.progress_log == ["шаг 1"]
        assert task.status == "paused"
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

async def test_repeated_restore_deduped_within_window(db_session):
    """Остаток «в копейки»: ping (единицы токенов) проходит, рабочий запрос — нет.
    Без дедупликации пользователь получал бы «баланс пополнен» каждые 10 минут."""
    await _cleanup(db_session)
    first = await _seed(db_session, progress_data={"chunks_done": 1})
    await db_session.commit()
    try:
        await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session), pinger=_ping(True)
        )
        # Задача снова упала по балансу и вернулась в paused — имитируем.
        await db_session.refresh(first)
        first.status = "paused"
        await db_session.commit()

        await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session), pinger=_ping(True)
        )

        events = (await db_session.execute(select(SystemEvent))).scalars().all()
        assert len(events) == 1, "второе событие в пределах окна — дубль"
        # Возобновлению дедупликация не мешает: задача снова в работе.
        await db_session.refresh(first)
        assert first.status == "pending"
    finally:
        await _cleanup(db_session)


async def test_restore_after_window_records_new_event(db_session):
    """Настоящее пополнение спустя время — событие должно прийти снова."""
    await _cleanup(db_session)
    old = SystemEvent(
        kind=KIND_BALANCE_RESTORED,
        payload={"resumed_task_ids": ["old"]},
        created_at=datetime.now(timezone.utc)
        - timedelta(minutes=rp.DEDUPE_WINDOW_MINUTES + 1),
    )
    db_session.add(old)
    task = await _seed(db_session, progress_data={"chunks_done": 1})
    await db_session.commit()
    try:
        await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session), pinger=_ping(True)
        )

        events = (await db_session.execute(select(SystemEvent))).scalars().all()
        assert len(events) == 2
        assert events[-1].payload == {"resumed_task_ids": [task.id]}
    finally:
        await _cleanup(db_session)


async def test_no_event_when_nothing_claimed(db_session, claude_api):
    """Параллельный тик перехватил задачу, пока этот ждал ответа на ping: захват
    не удался — ни job, ни события о пополнении (писать не о чем)."""
    await _cleanup(db_session)
    task = await _seed(db_session, progress_data={"chunks_done": 1})
    await db_session.commit()
    task_id = task.id

    async def ping_while_other_tick_claims(_kwargs):
        async with TestSessionLocal() as other:
            await other.execute(
                update(Task).where(Task.id == task_id).values(status="pending")
            )
            await other.commit()
        return claude_message("pong")

    claude_api(ping_while_other_tick_claims)
    try:
        claimed = await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session)
        )

        assert claimed == []
        db_session.expire_all()
        assert (await db_session.execute(select(SystemEvent))).scalars().all() == []
        assert (await db_session.execute(select(Job))).scalars().all() == []
    finally:
        await _cleanup(db_session)

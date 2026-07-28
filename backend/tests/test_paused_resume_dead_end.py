"""
Фаза 8 — тупик «задача на паузе не возобновляется никогда».

Симптом с прода (2026-07-28): ESTIMATE_FROM_LIST ушла в paused по балансу; после
пополнения счёта авто-возобновление не срабатывало, а кнопка «Продолжить сейчас»
отвечала «Не удалось возобновить задачу».

Причина: и ручной resume-эндпоинт, и resume_poller требовали resumable-чекпоинт.
Пауза же может случиться ДО первого чекпоинта (первая группа чанков в fast-режиме
или submit пачки в batch-режиме) — progress_data пуст, и задача мертва навсегда.

Контракт после фикса:
- paused БЕЗ чекпоинта → resume разрешён (перезапуск с нуля), поллер её берёт;
- failed/cancelled без чекпоинта → по-прежнему 409 (нечего продолжать);
- paused + _stage=batch_pending (пачка уже оплачена) → НЕ перезапуск, а возврат
  в processing: результаты доберёт batch_poller;
- process() не помечает batch-задачу completed сразу после submit;
- баланс, кончившийся при сборке пачки в batch_poller → paused, не failed.

План: plans/2026-07-21-resume-and-balance-pause.md, Фаза 8.
"""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, select

sys.modules.setdefault("fitz", MagicMock())

import app.services.batch_poller as bp  # noqa: E402
import app.services.resume_poller as rp  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.services.checkpoint import is_batch_pending  # noqa: E402
from app.services.claude_service import InsufficientBalanceError  # noqa: E402
from app.services.task_processor import TaskProcessor  # noqa: E402


# ---------------------------------------------------------------------------
# is_batch_pending — предикат «пачка отправлена и оплачена»
# ---------------------------------------------------------------------------

def test_is_batch_pending_variants():
    assert is_batch_pending({"_stage": "batch_pending", "batch_id": "msgbatch_1"}) is True
    # без batch_id перезапускать безопасно — пачки на серверах Anthropic нет
    assert is_batch_pending({"_stage": "batch_pending"}) is False
    assert is_batch_pending({"_stage": "claude_partial", "batch_id": "x"}) is False
    assert is_batch_pending({}) is False
    assert is_batch_pending(None) is False


# ---------------------------------------------------------------------------
# resume-эндпоинт
# ---------------------------------------------------------------------------

async def _seed_task(db, task_id, *, status, progress_data=None,
                     task_type="ESTIMATE_FROM_LIST") -> Task:
    task = Task(
        owner_id=1,
        id=task_id,
        user_role="user",
        task_type=task_type,
        status=status,
        estimation_status="not_applicable",
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_data=progress_data,
        error_message="Баланс API Anthropic исчерпан.",
    )
    db.add(task)
    await db.commit()
    return task


async def test_resume_paused_without_checkpoint_restarts(
    async_client, user_token, seed_users, db_session, monkeypatch
):
    """Главный баг: paused без чекпоинта → 200 + pending (раньше был 409)."""
    task_id = "d8000000-0000-0000-0000-000000000001"
    task = await _seed_task(db_session, task_id, status="paused", progress_data={})
    monkeypatch.setattr(
        "app.routers.tasks._run_task_in_background", AsyncMock(return_value=None)
    )
    try:
        resp = await async_client.post(
            f"/tasks/{task_id}/resume", headers={"Authorization": user_token}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "pending"

        await db_session.refresh(task)
        assert task.status == "pending"
        assert task.error_message is None

        jobs = (
            await db_session.execute(
                select(Job).where(Job.kind == "task.process")
            )
        ).scalars().all()
        assert any(j.payload == {"task_id": task_id} for j in jobs)
    finally:
        await db_session.execute(delete(Job))
        await db_session.execute(delete(Task).where(Task.id == task_id))
        await db_session.commit()


async def test_resume_paused_null_progress_data(
    async_client, user_token, seed_users, db_session, monkeypatch
):
    """progress_data = NULL (пауза на самом первом вызове Claude) — тоже возобновляема."""
    task_id = "d8000000-0000-0000-0000-000000000002"
    task = await _seed_task(db_session, task_id, status="paused", progress_data=None)
    monkeypatch.setattr(
        "app.routers.tasks._run_task_in_background", AsyncMock(return_value=None)
    )
    try:
        resp = await async_client.post(
            f"/tasks/{task_id}/resume", headers={"Authorization": user_token}
        )
        assert resp.status_code == 200, resp.text
        await db_session.refresh(task)
        assert task.status == "pending"
    finally:
        await db_session.execute(delete(Job))
        await db_session.execute(delete(Task).where(Task.id == task_id))
        await db_session.commit()


async def test_resume_paused_batch_pending_goes_to_processing(
    async_client, user_token, seed_users, db_session, monkeypatch
):
    """Пачка уже оплачена → processing (её доберёт batch_poller), без нового job."""
    task_id = "d8000000-0000-0000-0000-000000000003"
    task = await _seed_task(
        db_session, task_id, status="paused",
        progress_data={"_stage": "batch_pending", "batch_id": "msgbatch_x", "items": []},
    )
    monkeypatch.setattr(
        "app.routers.tasks._run_task_in_background", AsyncMock(return_value=None)
    )
    try:
        await db_session.execute(delete(Job))
        await db_session.commit()

        resp = await async_client.post(
            f"/tasks/{task_id}/resume", headers={"Authorization": user_token}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "processing"

        await db_session.refresh(task)
        assert task.status == "processing"
        # чекпоинт batch_pending сохранён — поллер найдёт задачу по нему
        assert task.progress_data["_stage"] == "batch_pending"

        jobs = (
            await db_session.execute(select(Job).where(Job.kind == "task.process"))
        ).scalars().all()
        assert jobs == [], "batch-задачу нельзя ставить в очередь на пересчёт"
    finally:
        await db_session.execute(delete(Job))
        await db_session.execute(delete(Task).where(Task.id == task_id))
        await db_session.commit()


async def test_resume_failed_without_checkpoint_still_409(
    async_client, user_token, seed_users, db_session
):
    """Регрессия: для failed пустой прогресс по-прежнему = нечего продолжать."""
    task_id = "d8000000-0000-0000-0000-000000000004"
    await _seed_task(db_session, task_id, status="failed", progress_data={})
    try:
        resp = await async_client.post(
            f"/tasks/{task_id}/resume", headers={"Authorization": user_token}
        )
        assert resp.status_code == 409
        assert "прогресс" in resp.json()["detail"].lower()
    finally:
        await db_session.execute(delete(Task).where(Task.id == task_id))
        await db_session.commit()


# ---------------------------------------------------------------------------
# resume_poller
# ---------------------------------------------------------------------------

def _same_session_factory(session):
    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    return lambda: _Ctx()


async def _ping_ok() -> dict:
    """Баланс есть — поллер должен возобновлять. Инъекция вместо реального
    api_ping, чтобы тест не ходил в сеть."""
    return {"ok": True, "is_balance_error": False, "status_code": 200, "error": None}


async def test_poller_resumes_paused_without_checkpoint(db_session):
    """Авто-возобновление: paused без чекпоинта → pending + durable job."""
    await db_session.execute(delete(Job))
    await db_session.commit()
    task_id = "d8000000-0000-0000-0000-000000000005"
    task = await _seed_task(db_session, task_id, status="paused", progress_data={})
    try:
        claimed = await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session), pinger=_ping_ok
        )
        assert claimed == [task_id]
        await db_session.refresh(task)
        assert task.status == "pending"

        jobs = (
            await db_session.execute(select(Job).where(Job.kind == "task.process"))
        ).scalars().all()
        assert len(jobs) == 1
    finally:
        await db_session.execute(delete(Job))
        await db_session.execute(delete(Task).where(Task.id == task_id))
        await db_session.commit()


async def test_poller_returns_batch_task_to_processing(db_session):
    """paused + batch_pending → processing без job (пачка уже оплачена)."""
    await db_session.execute(delete(Job))
    await db_session.commit()
    task_id = "d8000000-0000-0000-0000-000000000006"
    task = await _seed_task(
        db_session, task_id, status="paused",
        progress_data={"_stage": "batch_pending", "batch_id": "msgbatch_y"},
    )
    try:
        claimed = await rp.resume_paused_tasks(
            session_factory=_same_session_factory(db_session), pinger=_ping_ok
        )
        assert claimed == [], "batch-задача не должна попадать в пересчёт"
        await db_session.refresh(task)
        assert task.status == "processing"
        assert task.error_message is None

        jobs = (
            await db_session.execute(select(Job).where(Job.kind == "task.process"))
        ).scalars().all()
        assert jobs == []
    finally:
        await db_session.execute(delete(Job))
        await db_session.execute(delete(Task).where(Task.id == task_id))
        await db_session.commit()


# ---------------------------------------------------------------------------
# process(): batch-задача не завершается сразу после submit
# ---------------------------------------------------------------------------

async def test_process_leaves_batch_task_in_processing(db_session, monkeypatch):
    """После submit пачки задача остаётся processing — иначе batch_poller
    (ищет processing + batch_pending) никогда её не досчитает."""
    task_id = "d8000000-0000-0000-0000-000000000007"
    task = await _seed_task(
        db_session, task_id, status="pending",
        progress_data={"_stage": "batch_pending", "batch_id": "msgbatch_z"},
    )
    try:
        processor = TaskProcessor(task_id, db_session)
        # Обработчик имитирует batch-путь: чекпоинт уже в БД, шаг 3 не выполнялся.
        monkeypatch.setattr(
            processor, "_handle_estimate_from_list", AsyncMock(return_value=None)
        )
        auto_fill = AsyncMock(return_value=None)
        monkeypatch.setattr(processor, "_auto_fill_estimate_slot", auto_fill)

        await processor.process()

        await db_session.refresh(task)
        assert task.status == "processing", "batch-задача не завершена — результатов ещё нет"
        auto_fill.assert_not_awaited()
    finally:
        await db_session.execute(delete(Task).where(Task.id == task_id))
        await db_session.commit()


async def test_process_completes_non_batch_task(db_session, monkeypatch):
    """Регрессия: обычная (fast) задача по-прежнему завершается completed."""
    task_id = "d8000000-0000-0000-0000-000000000008"
    task = await _seed_task(
        db_session, task_id, status="pending",
        progress_data={"_stage": "pre_excel"},
    )
    try:
        processor = TaskProcessor(task_id, db_session)
        monkeypatch.setattr(
            processor, "_handle_estimate_from_list", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(
            processor, "_auto_fill_estimate_slot", AsyncMock(return_value=None)
        )

        await processor.process()

        await db_session.refresh(task)
        assert task.status == "completed"
    finally:
        await db_session.execute(delete(Task).where(Task.id == task_id))
        await db_session.commit()


# ---------------------------------------------------------------------------
# batch_poller: баланс на сборке пачки → paused, не failed
# ---------------------------------------------------------------------------

async def test_batch_poller_balance_error_pauses(db_session, monkeypatch):
    task_id = "d8000000-0000-0000-0000-000000000009"
    task = await _seed_task(
        db_session, task_id, status="processing",
        progress_data={"_stage": "batch_pending", "batch_id": "msgbatch_bal"},
    )
    try:
        monkeypatch.setattr(bp, "poll_claude_batch", AsyncMock(return_value="ended"))
        monkeypatch.setattr(
            TaskProcessor,
            "resume_from_batch",
            AsyncMock(side_effect=InsufficientBalanceError("нет денег")),
        )

        await bp._process_one(task_id, db_session)

        await db_session.refresh(task)
        assert task.status == "paused"
        assert "аланс" in (task.error_message or "")
        # чекпоинт пачки не потерян — после пополнения соберём те же результаты
        assert task.progress_data["_stage"] == "batch_pending"
    finally:
        await db_session.execute(delete(Task).where(Task.id == task_id))
        await db_session.commit()

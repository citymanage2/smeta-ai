"""
Phase 5 — периодический поллер batch-задач.

План: plans/2026-07-21-estimate-processing-modes.md, Phase 5.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.services.batch_poller as bp
import app.services.claude_service as cs
from app.models.task import Task
from tests.helpers.anthropic_api import claude_message, server_error


async def _seed(db, *, status="processing", stage="batch_pending", batch_id="msgbatch_1") -> Task:
    t = Task(
        user_role="user",
        task_type="ESTIMATE_FROM_LIST",
        status=status,
        input_files=[],
        input_file_data=[],
        chat_history=[],
        progress_data={
            "_stage": stage,
            "batch_id": batch_id,
            "items": [],
            "matched": {},
            "unmatched": {},
            "current_date": "21.07.2026",
        },
    )
    db.add(t)
    await db.flush()
    await db.refresh(t)
    return t


async def test_find_batch_pending_filters(db_session):
    t1 = await _seed(db_session, batch_id="b1")
    await _seed(db_session, stage="pre_excel", batch_id="b2")  # не batch_pending
    ids = await bp._find_batch_pending_ids(db_session)
    assert ids == [t1.id]


async def test_cancelled_cancels_batch_and_clears_stage(db_session, monkeypatch):
    t = await _seed(db_session, status="cancelled")
    cancel_mock = AsyncMock()
    poll_mock = AsyncMock()
    monkeypatch.setattr(bp, "cancel_claude_batch", cancel_mock)
    monkeypatch.setattr(bp, "poll_claude_batch", poll_mock)

    await bp._process_one(t.id, db_session)

    cancel_mock.assert_awaited_once_with("msgbatch_1")
    poll_mock.assert_not_called()
    await db_session.refresh(t)
    assert (t.progress_data or {}).get("_stage") == "batch_cancelled"


# ---------------------------------------------------------------------------
# Тик поллера по отправленной пачке: прогон на тестовой БД, подменён только
# Anthropic API (статус пачки и её результаты).
# ---------------------------------------------------------------------------

class _Batches:
    """`messages.batches` Anthropic: статус и результаты пачки задаёт тест."""

    def __init__(self) -> None:
        self.status = "in_progress"
        self.answer: dict = {}
        self.results_error = None

    async def create(self, requests):
        return SimpleNamespace(id="msgbatch_poll")

    async def retrieve(self, batch_id):
        return SimpleNamespace(id=batch_id, processing_status=self.status)

    async def results(self, batch_id):
        if self.results_error is not None:
            raise self.results_error
        entry = SimpleNamespace(
            custom_id="chunk-0",
            result=SimpleNamespace(type="succeeded", message=claude_message(self.answer)),
        )

        async def _stream():
            yield entry

        return _stream()


@pytest.mark.parametrize(
    "poll_status, results_fail, task_status, stage",
    [
        ("in_progress", False, "processing", "batch_pending"),  # ещё считается — ждём
        ("ended", False, "completed", None),                    # готово — смета собрана
        ("ended", True, "failed", "batch_pending"),              # сбор упал — ошибка видна
        ("expired", False, "failed", "batch_pending"),           # пачка истекла
    ],
)
async def test_poll_tick_moves_task_by_batch_status(
    processor_env, claude_api, app_sessions, poll_status, results_fail, task_status, stage,
):
    ai = claude_api()  # добора нет: пачка оценила единственную позицию
    batches = _Batches()
    cs._get_client().messages.batches = batches
    task = await processor_env.estimate_task(
        [{"type": "Работа", "name": "Кладка стен из кирпича", "unit": "м3", "quantity": 12}],
        processing_mode="batch",
    )
    task = await processor_env.run(task)
    assert task.progress_data["_stage"] == "batch_pending"

    batches.status = poll_status
    batches.answer = {"items": [{"id": 0, "type": "Работа", "work_price": 4500}]}
    if results_fail:
        batches.results_error = server_error(500)

    await bp.poll_batch_tasks(app_sessions)

    task = await processor_env.reload(task)
    assert task.status == task_status
    assert (task.progress_data or {}).get("_stage") == stage
    assert ai.calls == []
    if task_status == "completed":
        (item,) = await processor_env.estimate_items(task)
        assert item["work_price"] == 4500
    if task_status == "failed":
        assert task.error_message

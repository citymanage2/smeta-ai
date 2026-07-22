"""
Phase 5 — периодический поллер batch-задач.

План: plans/2026-07-21-estimate-processing-modes.md, Phase 5.
"""
import sys
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("fitz", MagicMock())

import app.services.batch_poller as bp  # noqa: E402
from app.services.task_processor import TaskProcessor  # noqa: E402
from app.models.task import Task  # noqa: E402


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


async def test_ended_runs_resume_and_completes(db_session, monkeypatch):
    t = await _seed(db_session)
    monkeypatch.setattr(bp, "poll_claude_batch", AsyncMock(return_value="ended"))
    monkeypatch.setattr(TaskProcessor, "resume_from_batch", AsyncMock())
    monkeypatch.setattr(TaskProcessor, "_auto_fill_estimate_slot", AsyncMock())
    update_mock = AsyncMock()
    monkeypatch.setattr(TaskProcessor, "update_status", update_mock)

    await bp._process_one(t.id, db_session)

    TaskProcessor.resume_from_batch.assert_awaited_once()
    update_mock.assert_awaited_once_with("completed")


async def test_in_progress_is_noop(db_session, monkeypatch):
    t = await _seed(db_session)
    monkeypatch.setattr(bp, "poll_claude_batch", AsyncMock(return_value="in_progress"))
    monkeypatch.setattr(TaskProcessor, "resume_from_batch", AsyncMock())

    await bp._process_one(t.id, db_session)

    TaskProcessor.resume_from_batch.assert_not_called()


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


async def test_ended_resume_failure_marks_failed(db_session, monkeypatch):
    t = await _seed(db_session)
    monkeypatch.setattr(bp, "poll_claude_batch", AsyncMock(return_value="ended"))
    monkeypatch.setattr(TaskProcessor, "resume_from_batch", AsyncMock(side_effect=RuntimeError("boom")))
    update_mock = AsyncMock()
    monkeypatch.setattr(TaskProcessor, "update_status", update_mock)

    await bp._process_one(t.id, db_session)

    # статус выставлен failed с сообщением
    assert update_mock.await_args.args[0] == "failed"

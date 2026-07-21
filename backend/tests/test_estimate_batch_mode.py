"""
Phase 4 — batch-режим ESTIMATE_FROM_LIST в TaskProcessor.

_submit_estimate_batch: отправляет пачку, пишет чекпоинт _stage=batch_pending, НЕ делает step3.
resume_from_batch: собирает результаты пачки → claude_results → step3 (через pre_excel-путь).

План: plans/2026-07-21-estimate-processing-modes.md, Phase 4.
"""
import sys
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("fitz", MagicMock())

from app.services.task_processor import TaskProcessor  # noqa: E402


def _proc() -> TaskProcessor:
    p = TaskProcessor("tid-batch", db=MagicMock())
    p.update_progress = AsyncMock(return_value=None)
    p._save_progress_data = AsyncMock(return_value=None)
    p._cache_priced_item = AsyncMock(return_value=None)
    return p


# --------------------------------------------------------------------------
# submit — отправляет пачку и пишет чекпоинт batch_pending, без step3
# --------------------------------------------------------------------------

async def test_submit_estimate_batch_writes_checkpoint(monkeypatch):
    p = _proc()
    p._run_estimate_step3 = AsyncMock()  # не должен вызываться

    submit_mock = AsyncMock(return_value="msgbatch_xyz")
    monkeypatch.setattr("app.services.task_processor.submit_claude_batch", submit_mock, raising=False)
    monkeypatch.setattr(
        "app.services.task_processor.build_batch_request",
        lambda **kw: {"custom_id": kw["custom_id"], "params": {}},
        raising=False,
    )

    task = MagicMock()
    items = [{"_id": 0, "type": "Работа", "name": "A", "unit": "м2", "quantity": 1}]
    matched = {}
    unmatched = {0: items[0]}
    chunks = [[items[0]]]

    await p._submit_estimate_batch(task, items, matched, unmatched, "21.07.2026", chunks)

    # пачка отправлена
    submit_mock.assert_awaited_once()
    # чекпоинт batch_pending сохранён с batch_id
    saved = p._save_progress_data.await_args.args[0]
    assert saved["_stage"] == "batch_pending"
    assert saved["batch_id"] == "msgbatch_xyz"
    assert saved["unmatched"] == {"0": items[0]}
    assert saved["current_date"] == "21.07.2026"
    # step3 НЕ вызван
    p._run_estimate_step3.assert_not_called()


# --------------------------------------------------------------------------
# resume — собирает результаты пачки, наполняет claude_results, зовёт step3
# --------------------------------------------------------------------------

async def test_resume_from_batch_collects_and_runs_step3(monkeypatch):
    p = _proc()
    p._run_estimate_step3 = AsyncMock()

    # collect_claude_batch → результат по custom_id с JSON-текстом
    collect_mock = AsyncMock(return_value={
        "chunk-0": {"text": '{"items": [{"id": 0, "type": "Работа", "name": "A", "work_price": 500}]}', "error": None},
        "chunk-1": {"text": None, "error": "errored"},  # ошибочный — пропускается
    })
    monkeypatch.setattr("app.services.task_processor.collect_claude_batch", collect_mock, raising=False)

    task = MagicMock()
    task.progress_data = {
        "_stage": "batch_pending",
        "batch_id": "msgbatch_xyz",
        "items": [{"_id": 0, "type": "Работа", "name": "A"}],
        "matched": {},
        "unmatched": {"0": {"_id": 0}},
        "current_date": "21.07.2026",
    }

    await p.resume_from_batch(task)

    collect_mock.assert_awaited_once()
    # step3 вызван с восстановленными items и claude_results (id=0 присутствует)
    p._run_estimate_step3.assert_awaited_once()
    call_args = p._run_estimate_step3.await_args.args
    _task, _items, _matched, _claude = call_args
    assert 0 in _claude
    assert _claude[0]["work_price"] == 500
    # цена ушла в кеш
    p._cache_priced_item.assert_awaited()

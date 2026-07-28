"""Паритет batch-режима с fast: позиций без цены в смете быть не должно.

Было: resume_from_batch делал одну проходку — что пачка пропустила или вернула
с нулевой ценой, так и уходило в Excel пустым (в fast-режиме для этого есть
отдельный проход-добор).

Стало: тот же добор синхронно, чанками ESTIMATE_RETRY_CHUNK, тем же
_fetch_price_chunk, что и в fast.

План: plans/2026-07-28-снижение-числа-вызовов-claude.md, Фаза 3.
"""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.services.task_processor import TaskProcessor  # noqa: E402


def _item(gidx: int, type_: str = "Работа") -> dict:
    return {
        "_id": gidx, "type": type_, "name": f"Позиция {gidx}",
        "unit": "м3", "quantity": 1,
    }


# --------------------------------------------------------------------------
# _ids_without_price — общий предикат «цены нет» для fast и batch
# --------------------------------------------------------------------------

def test_ids_without_price_covers_missing_and_null():
    unmatched = {0: _item(0), 1: _item(1), 2: _item(2, "Материал"), 3: _item(3)}
    claude_results = {
        1: {"id": 1, "work_price": 0},        # вернулся с нулевой ценой
        2: {"id": 2, "material_price": 500},  # нормальный
        3: {"id": 3, "work_price": 700},      # нормальный
        # 0 — пропущен вовсе
    }
    assert TaskProcessor._ids_without_price(unmatched, claude_results) == [0, 1]


def test_ids_without_price_empty_when_all_priced():
    unmatched = {0: _item(0), 1: _item(1, "Материал")}
    claude_results = {0: {"work_price": 100}, 1: {"material_price": 200}}
    assert TaskProcessor._ids_without_price(unmatched, claude_results) == []


# --------------------------------------------------------------------------
# resume_from_batch — добор непосчитанных позиций после пачки
# --------------------------------------------------------------------------

def _proc_for_batch(monkeypatch, unmatched: dict, batch_results: list[dict]):
    p = TaskProcessor("tid-batch-parity", db=MagicMock())
    p.update_progress = AsyncMock()
    p._save_progress_data = AsyncMock()
    p._cache_priced_item = AsyncMock()
    p._check_cancelled = AsyncMock()
    p._run_estimate_step3 = AsyncMock()

    async def fake_collect(batch_id, task_id=None, db=None):
        import json
        return {"chunk-0": {"text": json.dumps({"items": batch_results}), "error": None}}

    monkeypatch.setattr(
        "app.services.task_processor.collect_claude_batch", fake_collect
    )

    task = MagicMock()
    task.progress_data = {
        "batch_id": "msgbatch_x",
        "items": [dict(it) for it in unmatched.values()],
        "matched": {},
        "unmatched": {str(k): v for k, v in unmatched.items()},
        "current_date": "01.01.2026",
    }
    return p, task


async def test_resume_from_batch_fills_missing_positions(monkeypatch):
    """Пачка вернула цену только для одной из трёх позиций — две добираем."""
    unmatched = {0: _item(0), 1: _item(1), 2: _item(2)}
    batch_results = [
        {"id": 0, "work_price": 100},
        {"id": 1, "work_price": None},  # нулевая цена — тоже проблема
        # id=2 пачка пропустила
    ]
    p, task = _proc_for_batch(monkeypatch, unmatched, batch_results)

    asked: list[list[int]] = []

    async def fake_fetch(chunk, current_date, label):
        asked.append([it["_id"] for it in chunk])
        return [{"id": it["_id"], "work_price": 900} for it in chunk]

    p._fetch_price_chunk = fake_fetch

    await p.resume_from_batch(task)

    assert asked == [[1, 2]], f"добор запрошен неверно: {asked}"
    _, _, _, claude_results = p._run_estimate_step3.await_args.args
    assert claude_results[1]["work_price"] == 900
    assert claude_results[2]["work_price"] == 900
    assert claude_results[0]["work_price"] == 100  # цену из пачки не перетёрли


async def test_resume_from_batch_skips_retry_when_all_priced(monkeypatch):
    """Пачка посчитала всё — лишних вызовов Claude быть не должно."""
    unmatched = {0: _item(0), 1: _item(1)}
    batch_results = [{"id": 0, "work_price": 100}, {"id": 1, "work_price": 200}]
    p, task = _proc_for_batch(monkeypatch, unmatched, batch_results)

    p._fetch_price_chunk = AsyncMock(side_effect=AssertionError("добор не нужен"))

    await p.resume_from_batch(task)

    _, _, _, claude_results = p._run_estimate_step3.await_args.args
    assert claude_results[0]["work_price"] == 100
    assert claude_results[1]["work_price"] == 200


async def test_resume_from_batch_checkpoints_before_failing(monkeypatch):
    """Добор упал по балансу → собранное фиксируется, задача уходит в паузу."""
    from app.services.claude_service import InsufficientBalanceError

    unmatched = {0: _item(0), 1: _item(1)}
    batch_results = [{"id": 0, "work_price": 100}]
    p, task = _proc_for_batch(monkeypatch, unmatched, batch_results)

    async def boom(chunk, current_date, label):
        raise InsufficientBalanceError("no money")

    p._fetch_price_chunk = boom

    with pytest.raises(InsufficientBalanceError):
        await p.resume_from_batch(task)

    saved = [c.args[0] for c in p._save_progress_data.await_args_list]
    assert any(s.get("_stage") == "pre_excel" for s in saved), saved
    p._run_estimate_step3.assert_not_awaited()

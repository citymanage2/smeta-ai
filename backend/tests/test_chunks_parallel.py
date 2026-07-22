"""
Phase 3 — примитив параллельной обработки чанков TaskProcessor._run_chunks_parallel.

Воркеры НЕ обращаются к self.db; общий cancel-watcher отменяет их при отмене задачи.
План: plans/2026-07-21-estimate-processing-modes.md, Phase 3.
"""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# fitz (PyMuPDF) может отсутствовать в тестовом окружении — мок до импорта task_processor
sys.modules.setdefault("fitz", MagicMock())

from app.services.task_processor import TaskProcessor, TaskCancelledError


def _proc() -> TaskProcessor:
    p = TaskProcessor("tid-1", db=MagicMock())
    p._check_cancelled = AsyncMock(return_value=None)  # по умолчанию не отменена
    return p


async def test_results_preserve_order():
    p = _proc()

    def make(i):
        async def _w():
            await asyncio.sleep(0.01 * ((5 - i)))  # разный порядок завершения
            return i
        return _w

    workers = [make(i) for i in range(5)]
    results = await p._run_chunks_parallel(workers, concurrency=4)
    assert results == [0, 1, 2, 3, 4]


async def test_concurrency_is_bounded():
    p = _proc()
    state = {"cur": 0, "max": 0}

    def make():
        async def _w():
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
            await asyncio.sleep(0.02)
            state["cur"] -= 1
            return None
        return _w

    workers = [make() for _ in range(10)]
    await p._run_chunks_parallel(workers, concurrency=3)
    assert state["max"] <= 3


async def test_empty_workers_returns_empty():
    p = _proc()
    assert await p._run_chunks_parallel([], concurrency=4) == []


async def test_cancellation_raises_and_cancels_workers():
    p = _proc()
    p._check_cancelled = AsyncMock(side_effect=TaskCancelledError("stop"))
    finished = {"count": 0}

    def make():
        async def _w():
            await asyncio.sleep(5.0)  # долгий — должен быть отменён
            finished["count"] += 1
            return "done"
        return _w

    workers = [make() for _ in range(4)]
    with pytest.raises(TaskCancelledError):
        await p._run_chunks_parallel(workers, concurrency=4, cancel_check_interval=0.02)
    # воркеры отменены, не досчитались
    assert finished["count"] == 0


async def test_real_exception_propagates():
    p = _proc()

    def ok():
        async def _w():
            return "ok"
        return _w

    def boom():
        async def _w():
            raise RuntimeError("Баланс API Anthropic меньше 0")
        return _w

    with pytest.raises(RuntimeError, match="Баланс"):
        await p._run_chunks_parallel([ok(), boom()], concurrency=4)

"""
Phase 2b — промежуточный чекпоинт шага 2 ESTIMATE_FROM_LIST (fast/sync).

_pending_chunks: пропускает позиции, уже посчитанные Claude (resume без повторной
                 траты токенов).
_save_claude_partial: пишет чекпоинт _stage="claude_partial" с накопленными
                      claude_results.

План: plans/2026-07-21-resume-and-balance-pause.md, Фаза 2б.
"""
import sys
from unittest.mock import AsyncMock, MagicMock

sys.modules.setdefault("fitz", MagicMock())

from app.services.task_processor import TaskProcessor  # noqa: E402


def _proc() -> TaskProcessor:
    p = TaskProcessor("tid-resume", db=MagicMock())
    p.update_progress = AsyncMock(return_value=None)
    p._save_progress_data = AsyncMock(return_value=None)
    return p


# --------------------------------------------------------------------------
# _pending_chunks — исключает уже посчитанные позиции, дробит частичные чанки
# --------------------------------------------------------------------------

def test_pending_chunks_excludes_done_ids():
    chunks = [
        [{"_id": 0}, {"_id": 1}],   # 0 done, 1 pending → остаётся [1]
        [{"_id": 2}, {"_id": 3}],   # оба done → чанк выкидывается
        [{"_id": 4}],               # pending → остаётся
    ]
    pending = TaskProcessor._pending_chunks(chunks, {0, 2, 3})
    assert pending == [[{"_id": 1}], [{"_id": 4}]]


def test_pending_chunks_empty_when_all_done():
    chunks = [[{"_id": 0}], [{"_id": 1}]]
    assert TaskProcessor._pending_chunks(chunks, {0, 1}) == []


def test_pending_chunks_all_when_none_done():
    chunks = [[{"_id": 0}, {"_id": 1}]]
    assert TaskProcessor._pending_chunks(chunks, set()) == [[{"_id": 0}, {"_id": 1}]]


# --------------------------------------------------------------------------
# _save_claude_partial — чекпоинт claude_partial с накопленными результатами
# --------------------------------------------------------------------------

async def test_save_claude_partial_writes_checkpoint():
    p = _proc()
    items = [{"_id": 0, "name": "A"}, {"_id": 1, "name": "B"}]
    matched = {1: {"work_price": 100}}
    claude_results = {0: {"id": 0, "work_price": 500}}

    await p._save_claude_partial(items, matched, claude_results)

    saved = p._save_progress_data.await_args.args[0]
    assert saved["_stage"] == "claude_partial"
    assert saved["items"] == items
    # int-ключи сериализуются в строки (как в pre_excel / batch)
    assert saved["matched"] == {"1": {"work_price": 100}}
    assert saved["claude_results"] == {"0": {"id": 0, "work_price": 500}}

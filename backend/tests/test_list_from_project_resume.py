"""
Фаза 2 — по-чанковый чекпоинт и resume для LIST_FROM_PROJECT.

Контракт:
- Проход 1 (извлечение позиций из PDF по чанкам) пишет чекпоинт после каждого
  чанка (`chunks_done`, `_stage="pass1"`); resume продолжает с необработанных
  частей, не пересчитывая уже обработанные.
- После прохода 1 ставится `_stage="pass1_done"`, чтобы пауза в проходе 2 не
  перезапускала дорогой проход 1.
- Баланс API (InsufficientBalanceError) в любом чанке НЕ проглатывается, а
  пробрасывается вверх (→ пауза) — раньше non-first чанк молча пропускался.

План: plans/2026-07-21-resume-and-balance-pause.md, Фаза 2.
"""
import base64
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.modules.setdefault("fitz", MagicMock())

import app.services.task_processor as tp  # noqa: E402
from app.services.task_processor import TaskProcessor  # noqa: E402
from app.services.claude_service import InsufficientBalanceError  # noqa: E402


def _item(name, qty=1):
    return {"name": name, "type": "work", "quantity": qty}


def _make_proc(monkeypatch, *, chunks, claude_side_effect):
    """TaskProcessor с замоканными PDF-чанкингом, Claude и побочными методами."""
    p = TaskProcessor("tid-lfp", db=MagicMock())
    p.update_progress = AsyncMock(return_value=None)
    p._save_progress_data = AsyncMock(return_value=None)
    p.save_result = AsyncMock(return_value=None)
    p._create_initial_generic_version = AsyncMock(return_value=None)
    p._load_input_files = AsyncMock(return_value=[
        {"mime_type": "application/pdf", "content_b64": base64.b64encode(b"pdf").decode()}
    ])
    p._interruptible_claude_json_with_retry = AsyncMock(side_effect=claude_side_effect)

    monkeypatch.setattr(tp, "chunk_project_pdf", lambda _b: chunks)
    monkeypatch.setattr(tp, "normalize_items", lambda items: items)
    monkeypatch.setattr(tp, "generate_list", lambda *a, **k: b"xlsx-bytes")
    return p


def _chunks(n):
    return [{"text": f"t{i}", "image_pages": []} for i in range(n)]


# ---------------------------------------------------------------------------
# Resume прохода 1 — пропуск уже обработанных чанков
# ---------------------------------------------------------------------------

async def test_resume_pass1_skips_done_chunks(monkeypatch):
    # 2 чанка, chunks_done=1 → обрабатываем только чанк с индексом 1.
    task = SimpleNamespace(
        task_type="LIST_FROM_PROJECT",
        name=None,
        progress_data={
            "chunks_done": 1,
            "total_chunks": 2,
            "items": [_item("A")],
            "_stage": "pass1",
        },
    )
    p = _make_proc(
        monkeypatch,
        chunks=_chunks(2),
        claude_side_effect=[{"items": [_item("B")]}],  # только для чанка 1
    )

    await p._handle_list_from_project(task)

    # Claude вызван ровно один раз (первый чанк пропущен по чекпоинту).
    assert p._interruptible_claude_json_with_retry.await_count == 1
    # Результат сформирован из восстановленных + новых позиций.
    p.save_result.assert_awaited_once()
    saved_stages = [c.args[0].get("_stage") for c in p._save_progress_data.await_args_list]
    assert "pass1_done" in saved_stages


async def test_resume_pass1_done_skips_pass1_entirely(monkeypatch):
    # _stage=pass1_done + все позиции с объёмом → ни один вызов Claude не нужен.
    task = SimpleNamespace(
        task_type="LIST_FROM_PROJECT",
        name=None,
        progress_data={
            "chunks_done": 2,
            "total_chunks": 2,
            "items": [_item("A"), _item("B")],
            "_stage": "pass1_done",
        },
    )
    p = _make_proc(monkeypatch, chunks=_chunks(2), claude_side_effect=[])

    await p._handle_list_from_project(task)

    assert p._interruptible_claude_json_with_retry.await_count == 0
    p.save_result.assert_awaited_once()


# ---------------------------------------------------------------------------
# Баланс в non-first чанке прохода 1 → пробрасывается (не проглатывается)
# ---------------------------------------------------------------------------

async def test_balance_error_in_pass1_propagates(monkeypatch):
    task = SimpleNamespace(
        task_type="LIST_FROM_PROJECT",
        name=None,
        progress_data=None,
    )
    p = _make_proc(
        monkeypatch,
        chunks=_chunks(2),
        claude_side_effect=[
            {"items": [_item("A")]},                 # чанк 0 — ок
            InsufficientBalanceError("no money"),    # чанк 1 — баланс
        ],
    )

    with pytest.raises(InsufficientBalanceError):
        await p._handle_list_from_project(task)

    # Чекпоинт после успешного чанка 0 сохранён — resume продолжит с чанка 1.
    saved = [c.args[0] for c in p._save_progress_data.await_args_list]
    assert any(s.get("chunks_done") == 1 and s.get("_stage") == "pass1" for s in saved)
    # save_result НЕ вызывался — задача не завершилась, а ушла на паузу.
    p.save_result.assert_not_awaited()


async def test_first_chunk_failure_raises(monkeypatch):
    """Регрессия: падение самого первого чанка (не баланс) по-прежнему валит задачу."""
    task = SimpleNamespace(task_type="LIST_FROM_PROJECT", name=None, progress_data=None)
    p = _make_proc(
        monkeypatch,
        chunks=_chunks(2),
        claude_side_effect=[RuntimeError("boom")],  # чанк 0 падает
    )

    with pytest.raises(RuntimeError):
        await p._handle_list_from_project(task)

"""
Харденинг паузы по балансу Anthropic (доп. к test_balance_pause.py).

Закрывает два пробела в авто-возобновлении «деньги кончились → продолжить»:
1. Распознавание billing-ошибки было только по подстроке "credit balance".
   Через агрегатор/прокси (base_url) формулировка/код иные → расширяем список
   маркеров + статус 402 Payment Required. Держим КОНСЕРВАТИВНО: ложное
   срабатывание = задача уходит в paused и ретраится, а не честный failed.
2. Batch-режим (ESTIMATE_FROM_LIST) не переводил billing-ошибку при отправке
   пачки в paused (был failed), и до submit не было resumable-чекпоинта, из-за
   чего resume_poller не подхватил бы paused-задачу. Теперь:
   - submit_claude_batch мапит billing → InsufficientBalanceError;
   - _submit_estimate_batch сохраняет claude_partial ПЕРЕД отправкой.

План: plans/2026-07-21-resume-and-balance-pause.md (Фаза 7 — харденинг).
"""
import sys
from unittest.mock import AsyncMock, MagicMock

import httpx2
import anthropic
import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.services.claude_service import (  # noqa: E402
    call_claude,
    submit_claude_batch,
    InsufficientBalanceError,
    _is_insufficient_balance,
)
from app.services.task_processor import TaskProcessor  # noqa: E402


def _api_status_error(status_code: int, message: str) -> anthropic.APIStatusError:
    """Сфабриковать APIStatusError с заданным статусом и текстом в body.error.message."""
    body = {"error": {"type": "invalid_request_error", "message": message}}
    raw = httpx2.Response(
        status_code=status_code,
        headers={},
        content=b"{}",
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    return anthropic.APIStatusError(message, response=raw, body=body)


# ---------------------------------------------------------------------------
# _is_insufficient_balance — предикат распознавания «нет денег»
# ---------------------------------------------------------------------------

def test_402_is_balance_regardless_of_text():
    # 402 Payment Required — однозначный billing-статус.
    assert _is_insufficient_balance(402, "anything") is True
    assert _is_insufficient_balance(402) is True


@pytest.mark.parametrize(
    "text",
    [
        "Your credit balance is too low",
        "insufficient balance on account",
        "insufficient_quota",
        "недостаточно средств на счёте",
        "account is out of credit",
    ],
)
def test_balance_markers_detected(text):
    assert _is_insufficient_balance(400, text) is True


@pytest.mark.parametrize(
    "text",
    [
        "bad request: missing field",
        "rate limit exceeded",
        "quota exceeded, slow down",  # rate-limit-подобное — НЕ billing (нет маркера)
        "model not found",
    ],
)
def test_non_balance_not_flagged(text):
    # Консервативность: обычные 4xx НЕ считаются балансовыми.
    assert _is_insufficient_balance(400, text) is False


# ---------------------------------------------------------------------------
# call_claude — расширенное распознавание (не только "credit balance")
# ---------------------------------------------------------------------------

def _patch_client(monkeypatch, fake_create):
    """Подменить ленивый _get_client() фейковым клиентом с заданным messages.create."""
    fake_client = MagicMock()
    fake_client.messages.create = fake_create
    monkeypatch.setattr("app.services.claude_service._get_client", lambda: fake_client)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", AsyncMock())


async def test_call_claude_maps_402_to_balance(monkeypatch):
    async def fake_create(**kwargs):
        raise _api_status_error(402, "Payment Required")

    _patch_client(monkeypatch, fake_create)

    with pytest.raises(InsufficientBalanceError):
        await call_claude([{"role": "user", "content": "hi"}])


async def test_call_claude_maps_insufficient_quota(monkeypatch):
    async def fake_create(**kwargs):
        raise _api_status_error(400, "insufficient_quota: add funds")

    _patch_client(monkeypatch, fake_create)

    with pytest.raises(InsufficientBalanceError):
        await call_claude([{"role": "user", "content": "hi"}])


# ---------------------------------------------------------------------------
# submit_claude_batch — billing при отправке пачки → InsufficientBalanceError
# ---------------------------------------------------------------------------

async def test_submit_batch_maps_balance_error(monkeypatch):
    async def fake_create(**kwargs):
        raise _api_status_error(400, "Your credit balance is too low")

    fake_client = MagicMock()
    fake_client.messages.batches.create = fake_create
    monkeypatch.setattr(
        "app.services.claude_service._get_client", lambda: fake_client
    )

    with pytest.raises(InsufficientBalanceError):
        await submit_claude_batch([{"custom_id": "c-0", "params": {}}])


async def test_submit_batch_non_balance_error_propagates(monkeypatch):
    async def fake_create(**kwargs):
        raise _api_status_error(400, "invalid request shape")

    fake_client = MagicMock()
    fake_client.messages.batches.create = fake_create
    monkeypatch.setattr(
        "app.services.claude_service._get_client", lambda: fake_client
    )

    with pytest.raises(anthropic.APIStatusError):
        await submit_claude_batch([{"custom_id": "c-0", "params": {}}])


# ---------------------------------------------------------------------------
# _submit_estimate_batch — resumable-чекпоинт сохраняется ДО отправки
# ---------------------------------------------------------------------------

async def test_submit_estimate_batch_checkpoints_before_submit(monkeypatch):
    """Если билинг падает на отправке пачки, до этого уже сохранён claude_partial —
    иначе paused-задачу не подхватит resume_poller (batch_pending не resumable)."""
    p = TaskProcessor("tid-batch-hardening", db=MagicMock())
    saved: list[dict] = []

    async def fake_save(data):
        saved.append(data)

    p._save_progress_data = fake_save  # type: ignore[assignment]
    p.update_progress = AsyncMock()  # type: ignore[assignment]

    async def boom(_requests):
        raise InsufficientBalanceError("no money")

    monkeypatch.setattr("app.services.task_processor.submit_claude_batch", boom)

    item = {"_id": 0, "type": "Работа", "name": "Кладка", "unit": "м3", "quantity": 1}
    unmatched = {0: item}
    chunks = [[item]]

    with pytest.raises(InsufficientBalanceError):
        await p._submit_estimate_batch(
            task=MagicMock(),
            items=[item],
            matched_by_gidx={},
            unmatched_by_gidx=unmatched,
            current_date="01.01.2026",
            chunks=chunks,
        )

    # Resumable-чекпоинт сохранён ДО упавшей отправки; batch_pending — нет.
    assert any(s.get("_stage") == "claude_partial" for s in saved), saved
    assert not any(s.get("_stage") == "batch_pending" for s in saved), saved


# ---------------------------------------------------------------------------
# fix_empty_prices — оплаченные батчи не теряются при исчерпании баланса
# ---------------------------------------------------------------------------

def _proc_with_task(items: list[dict]) -> tuple[TaskProcessor, MagicMock]:
    """Процессор с замоканной БД: db.execute(...).scalar_one_or_none() → task."""
    task = MagicMock()
    task.progress_data = {"items": items}
    task.processing_mode = "fast"
    result = MagicMock()
    result.scalar_one_or_none.return_value = task
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    p = TaskProcessor("tid-fix-empty", db=db)
    p.update_progress = AsyncMock()  # type: ignore[assignment]
    p._check_cancelled = AsyncMock()  # type: ignore[assignment]
    return p, task


async def test_fix_empty_prices_saves_paid_batches_before_balance_pause(monkeypatch):
    """Первый батч оплачен и вернул цены, второй упал по балансу.

    Найденные цены должны быть сохранены ДО падения — иначе перезапуск задачи
    снова увидит их пустыми и оплатит те же позиции второй раз. С Фазы 5 они
    уходят в рабочую версию сметы (единый источник правды), а не в
    `progress_data`.
    """
    from app.services import estimate_store

    written: dict = {}

    async def fake_write_items(_db, _task, items_, **_kw):
        written["items"] = [dict(it) for it in items_]
        return None, 0.0

    monkeypatch.setattr(estimate_store, "write_items", fake_write_items)

    # 12 позиций → два батча (ESTIMATE_RETRY_CHUNK=10 + 2): первый успешный,
    # второй падает по балансу.
    from app.services.task_processor import ESTIMATE_RETRY_CHUNK

    size = ESTIMATE_RETRY_CHUNK
    items = [
        {"type": "Работа", "name": f"Работа {i}", "unit": "м3", "quantity": 1}
        for i in range(size + 2)
    ]
    p, task = _proc_with_task(items)

    calls = {"n": 0}

    async def fake_claude(messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"items": [{"id": i, "work_price": 100 + i} for i in range(size)]}
        raise InsufficientBalanceError("Баланс API Anthropic меньше 0")

    p._call_claude_json_with_retry = fake_claude  # type: ignore[assignment]

    with pytest.raises(InsufficientBalanceError):
        await p.fix_empty_prices()

    saved_items = written["items"]
    assert [it.get("work_price") for it in saved_items[:size]] == [
        100 + i for i in range(size)
    ]
    # Позиции из упавшего батча остались пустыми — их пересчитает resume.
    assert not saved_items[size].get("work_price")

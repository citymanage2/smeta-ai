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
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.services.claude_service import (  # noqa: E402
    submit_claude_batch,
    InsufficientBalanceError,
    _is_insufficient_balance,
)
from tests.helpers.anthropic_api import api_error, balance_error, prompt_text  # noqa: E402


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
# submit_claude_batch — billing при отправке пачки → InsufficientBalanceError
# ---------------------------------------------------------------------------

async def test_submit_batch_maps_balance_error(monkeypatch):
    async def fake_create(**kwargs):
        raise api_error(400, "Your credit balance is too low")

    fake_client = MagicMock()
    fake_client.messages.batches.create = fake_create
    monkeypatch.setattr(
        "app.services.claude_service._get_client", lambda: fake_client
    )

    with pytest.raises(InsufficientBalanceError):
        await submit_claude_batch([{"custom_id": "c-0", "params": {}}])


async def test_submit_batch_non_balance_error_propagates(monkeypatch):
    async def fake_create(**kwargs):
        raise api_error(400, "invalid request shape")

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

async def test_submit_estimate_batch_checkpoints_before_submit(
    processor_env, patch_claude_create
):
    """Пачка отклонена по балансу при отправке: задача на паузе, и в БД уже лежит
    возобновляемый чекпоинт claude_partial — иначе paused-задачу не подхватит
    resume_poller (batch_pending не возобновляется, а до отправки его и нет)."""
    submitted: list = []

    async def no_sync_calls(**kwargs):
        raise AssertionError("batch-режим не ходит в обычный messages.create")

    async def batches_create(**kwargs):
        submitted.append(kwargs["requests"])
        raise balance_error()

    client = patch_claude_create(no_sync_calls)
    client.messages.batches = SimpleNamespace(create=batches_create)
    task = await processor_env.estimate_task(
        [{"type": "Работа", "name": "Кладка", "unit": "м3", "quantity": 1}],
        processing_mode="batch",
    )

    task = await processor_env.run(task)

    assert task.status == "paused"
    assert len(submitted) == 1, "пачку отправляли ровно один раз"
    assert task.progress_data["_stage"] == "claude_partial"
    assert "batch_id" not in task.progress_data


# ---------------------------------------------------------------------------
# fix_empty_prices — оплаченные батчи не теряются при исчерпании баланса
# ---------------------------------------------------------------------------

async def test_fix_empty_prices_saves_paid_batches_before_balance_pause(
    processor_env, claude_api, api_sleeps
):
    """Первый батч оплачен и вернул цены, второй упал по балансу.

    Найденные цены должны быть сохранены ДО падения — иначе перезапуск задачи
    снова увидит их пустыми и оплатит те же позиции второй раз. Они уходят в
    рабочую версию сметы (единый источник правды), а не в `progress_data`.
    """
    from app.services import estimate_store

    # 12 позиций → два батча по 10 и 2: первый успешный, второй — пустой счёт.
    names = [f"Работа {i:02d}" for i in range(12)]
    task = await processor_env.task("ESTIMATE_FROM_LIST", status="completed")
    await estimate_store.write_items(processor_env.db, task, [
        {"type": "Работа", "name": name, "unit": "м3", "quantity": 1} for name in names
    ])

    def answer(kwargs):
        prompt = prompt_text(kwargs)
        if "Работа 10" in prompt:
            return balance_error()
        ids = [i for i, name in enumerate(names) if name in prompt]
        return {"items": [{"id": i, "work_price": 100 + i} for i in ids]}

    ai = claude_api(answer, repeat=True)

    with pytest.raises(InsufficientBalanceError):
        await processor_env.processor(task).fix_empty_prices()

    assert len(ai.calls) == 2
    items = await processor_env.estimate_items(task)
    by_name = {it["name"]: it.get("work_price") for it in items}
    assert [by_name[n] for n in names[:10]] == [100 + i for i in range(10)]
    # Позиции из упавшего батча остались пустыми — их пересчитает resume.
    assert not by_name["Работа 10"] and not by_name["Работа 11"]

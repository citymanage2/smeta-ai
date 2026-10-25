"""
Phase 4 — batch-режим ESTIMATE_FROM_LIST: отправка пачки.

Смета в batch-режиме отправляет ненайденные в прайсе позиции в Message Batches
API, пишет чекпоинт `_stage=batch_pending` и выходит, оставляя задачу в
`processing`: результатов ещё нет, смету достроит поллер
(`test_batch_poller.py`, `test_batch_retry_parity.py`).

Прогон настоящий, на тестовой БД; подменён только Anthropic API.

План: plans/2026-07-21-estimate-processing-modes.md, Phase 4.
"""
from types import SimpleNamespace

import app.services.claude_service as cs


class _Batches:
    """`messages.batches` Anthropic: принимает пачку и выдаёт её id."""

    def __init__(self) -> None:
        self.submitted: list[list[dict]] = []

    async def create(self, requests):
        self.submitted.append(list(requests))
        return SimpleNamespace(id="msgbatch_xyz")


async def test_submit_estimate_batch_writes_checkpoint(processor_env, claude_api):
    ai = claude_api()  # обычных вызовов ИИ в batch-режиме нет
    batches = _Batches()
    cs._get_client().messages.batches = batches
    task = await processor_env.estimate_task(
        [{"type": "Работа", "name": "Кладка стен из кирпича", "unit": "м3", "quantity": 12}],
        processing_mode="batch",
    )

    task = await processor_env.run(task)

    # Пачка ушла одна, позиция — в её запросе.
    (requests,) = batches.submitted
    (request,) = requests
    prompt = request["params"]["messages"][0]["content"]
    assert "Кладка стен из кирпича" in prompt
    assert ai.calls == []

    # Результатов ещё нет: задача ждёт поллера, а не завершена.
    assert task.status == "processing"
    saved = task.progress_data
    assert saved["_stage"] == "batch_pending"
    assert saved["batch_id"] == "msgbatch_xyz"
    (unmatched,) = saved["unmatched"].values()
    assert unmatched["name"] == "Кладка стен из кирпича"
    assert saved["current_date"]
    # Смета не собиралась: файла результата нет.
    assert await processor_env.results(task) == []

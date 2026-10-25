"""Паритет batch-режима с fast: позиций без цены в смете быть не должно.

Было: resume_from_batch делал одну проходку — что пачка пропустила или вернула
с нулевой ценой, так и уходило в Excel пустым (в fast-режиме для этого есть
отдельный проход-добор).

Стало: тот же добор синхронно, чанками ESTIMATE_RETRY_CHUNK, тем же
_fetch_price_chunk, что и в fast.

Сборка пачки гоняется целиком: смета отправляет пачку (batch-режим), поллер
видит её завершённой и достраивает смету — на тестовой БД, подменён только
Anthropic API (результаты пачки и обычные вызовы добора). Результат читается из
рабочей версии сметы, `progress_data` и кеша цен.

План: plans/2026-07-28-снижение-числа-вызовов-claude.md, Фаза 3.
"""
from types import SimpleNamespace

from sqlalchemy import select

import app.services.batch_poller as bp
import app.services.claude_service as cs
from app.models.price_cache import PriceCacheWork
from app.services.task_processor import TaskProcessor
from tests.helpers.anthropic_api import balance_error, claude_message


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
# Сборка пачки и добор непосчитанных позиций
# --------------------------------------------------------------------------

WORKS = ["Кладка стен из кирпича", "Штукатурка стен", "Окраска стен"]


def _work(name: str, **fields) -> dict:
    return {"type": "Работа", "name": name, "unit": "м2", "quantity": 10, **fields}


def _succeeded(custom_id: str, answer: dict) -> SimpleNamespace:
    return SimpleNamespace(
        custom_id=custom_id,
        result=SimpleNamespace(type="succeeded", message=claude_message(answer)),
    )


def _errored(custom_id: str) -> SimpleNamespace:
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type="errored"))


class _Batches:
    """`messages.batches` Anthropic: пачка принимается и сразу «готова»; что в ней
    оказалось — задаёт тест (`entries`)."""

    def __init__(self) -> None:
        self.submitted: list[list[dict]] = []
        self.entries: list = []

    async def create(self, requests):
        self.submitted.append(list(requests))
        return SimpleNamespace(id="msgbatch_parity")

    async def retrieve(self, batch_id):
        return SimpleNamespace(id=batch_id, processing_status="ended")

    async def results(self, batch_id):
        entries = list(self.entries)

        async def _stream():
            for entry in entries:
                yield entry

        return _stream()


async def _collect_batch(processor_env, app_sessions, claude_api, items, entries, *retry):
    """Отправить смету пачкой, «досчитать» пачку и дать поллеру её собрать.

    `retry` — ответы ИИ на добор (обычные вызовы `messages.create`).
    Возвращает задачу из БД, сценарий обычных вызовов ИИ и отправленную пачку.
    """
    ai = claude_api(*retry)
    batches = _Batches()
    cs._get_client().messages.batches = batches
    task = await processor_env.estimate_task(items, processing_mode="batch")
    task = await processor_env.run(task)
    assert task.progress_data["_stage"] == "batch_pending"

    batches.entries = entries
    await bp.poll_batch_tasks(app_sessions)
    return await processor_env.reload(task), ai, batches


async def _prices(processor_env, task) -> dict:
    return {it["name"]: it["work_price"] for it in await processor_env.estimate_items(task)}


async def test_resume_from_batch_fills_missing_positions(processor_env, app_sessions, claude_api):
    """Пачка вернула цену только для одной из трёх позиций — две добираем."""
    batch = [_succeeded("chunk-0", {"items": [
        {"id": 0, "type": "Работа", "work_price": 100},
        {"id": 1, "type": "Работа", "work_price": None},  # нулевая цена — тоже проблема
        # id=2 пачка пропустила
    ]})]
    retry = {"items": [
        {"id": 1, "type": "Работа", "work_price": 900},
        {"id": 2, "type": "Работа", "work_price": 900},
    ]}

    task, ai, _ = await _collect_batch(
        processor_env, app_sessions, claude_api, [_work(n) for n in WORKS], batch, retry,
    )

    assert task.status == "completed"
    assert await _prices(processor_env, task) == {
        "Кладка стен из кирпича": 100,  # цену из пачки не перетёрли
        "Штукатурка стен": 900,
        "Окраска стен": 900,
    }
    # Добор — один запрос, и в нём только позиции без цены.
    (_call,) = ai.calls
    prompt = ai.prompt(0)
    assert "Штукатурка стен" in prompt and "Окраска стен" in prompt
    assert "Кладка стен из кирпича" not in prompt


async def test_resume_from_batch_skips_retry_when_all_priced(processor_env, app_sessions, claude_api):
    """Пачка посчитала всё — лишних вызовов Claude быть не должно."""
    batch = [_succeeded("chunk-0", {"items": [
        {"id": 0, "type": "Работа", "work_price": 100},
        {"id": 1, "type": "Работа", "work_price": 200},
    ]})]

    task, ai, _ = await _collect_batch(
        processor_env, app_sessions, claude_api, [_work(n) for n in WORKS[:2]], batch,
    )

    assert task.status == "completed"
    assert await _prices(processor_env, task) == {"Кладка стен из кирпича": 100, "Штукатурка стен": 200}
    assert ai.calls == []


async def test_resume_from_batch_checkpoints_before_failing(processor_env, app_sessions, claude_api):
    """Добор упал по балансу → собранное фиксируется, задача уходит в паузу."""
    batch = [_succeeded("chunk-0", {"items": [{"id": 0, "type": "Работа", "work_price": 100}]})]

    task, ai, _ = await _collect_batch(
        processor_env, app_sessions, claude_api, [_work(n) for n in WORKS[:2]], batch,
        balance_error(),
    )

    assert task.status == "paused"
    # Оплаченная пачка в чекпоинте: возобновление соберёт смету из него, а не
    # отправит пачку заново.
    checkpoint = task.progress_data
    assert checkpoint["_stage"] == "pre_excel"
    assert checkpoint["claude_results"]["0"]["work_price"] == 100
    # Смета не собиралась.
    assert await processor_env.results(task) == []
    assert len(ai.calls) == 1


async def test_batch_prices_go_to_price_cache(processor_env, app_sessions, claude_api, db_session):
    """Цена из пачки оплачена — она ложится в кеш и пригодится следующей смете."""
    batch = [_succeeded("chunk-0", {"items": [{
        "id": 0, "type": "Работа", "name": "Кладка стен из кирпича", "unit": "м2",
        "work_price": 4500, "sources": "Подрядчик А: 4500 руб",
    }]})]

    task, _, _ = await _collect_batch(
        processor_env, app_sessions, claude_api, [_work(WORKS[0])], batch,
    )

    assert task.status == "completed"
    db_session.expire_all()
    cached = (await db_session.execute(
        select(PriceCacheWork).where(PriceCacheWork.name == "Кладка стен из кирпича")
    )).scalar_one()
    assert float(cached.price) == 4500


async def test_errored_batch_chunk_is_skipped_and_its_positions_retried(
    processor_env, app_sessions, claude_api,
):
    """Кусок пачки с ошибкой не роняет сборку: его позиции уходят в добор."""
    # Позиции на разных листах — два куска пачки: чанк не пересекает лист.
    items = [_work(WORKS[0], sheet="Раздел 1"), _work(WORKS[1], sheet="Раздел 2")]
    batch = [
        _errored("chunk-1"),
        _succeeded("chunk-0", {"items": [{"id": 0, "type": "Работа", "work_price": 100}]}),
    ]
    retry = {"items": [{"id": 1, "type": "Работа", "work_price": 300}]}

    task, ai, batches = await _collect_batch(
        processor_env, app_sessions, claude_api, items, batch, retry,
    )

    assert [r["custom_id"] for r in batches.submitted[0]] == ["chunk-0", "chunk-1"]
    assert task.status == "completed"
    assert await _prices(processor_env, task) == {"Кладка стен из кирпича": 100, "Штукатурка стен": 300}
    assert len(ai.calls) == 1 and "Штукатурка стен" in ai.prompt(0)

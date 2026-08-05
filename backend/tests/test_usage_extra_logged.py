"""Допзапросы к ИИ помечаются в журнале затрат отдельно от основной обработки.

План: `plans/2026-08-06-metriki-zatrat-po-stadiyam.md`, Фаза 2.

Одна стадия сметы тратит деньги дважды: сначала обработчик формирует файл,
потом человек доспрашивает ИИ из редактора — ищет цену строки, аналоги,
предложения по оптимизации. В карточке это две разные цифры, и перепутать их
нельзя: именно по разнице видно, где утекают деньги.

До этой фичи шесть из семи таких мест не писали вызов в журнал вовсе — не было
`task_id`/`db`, и `_log_api_call` молча выходил. Здесь проверяется, что вызов
доезжает до журнала и приходит с верным признаком.
"""
import pytest

# document_locks ссылается на workflow_cards — без этого импорта метаданные
# таблиц неполны, и фикстура create_tables падает при запуске файла отдельно.
from app.models.workflow_card import WorkflowCard  # noqa: F401
from app.services import analogs_service, price_service


class _Spy:
    """Подменяет call_claude и запоминает kwargs каждого вызова."""

    def __init__(self, reply: str = "{}"):
        self.reply = reply
        self.calls: list[dict] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append(kwargs)
        return self.reply


@pytest.mark.asyncio
async def test_analogs_search_logged_as_extra(monkeypatch):
    """Поиск аналогов идёт по уже сформированному документу → доп."""
    spy = _Spy('{"items": []}')
    monkeypatch.setattr(analogs_service, "call_claude", spy)

    await analogs_service._ask_batch(
        [{"row_id": "r1", "name": "Кирпич", "unit": "шт", "price": 25}],
        task_id="task-1",
        db=object(),
    )

    assert len(spy.calls) == 1
    assert spy.calls[0]["is_extra"] is True
    # Без task_id/db запись в журнал не создаётся вовсе — проверяем, что они едут.
    assert spy.calls[0]["task_id"] == "task-1"
    assert spy.calls[0]["db"] is not None


@pytest.mark.asyncio
async def test_web_search_work_price_logged_as_extra(monkeypatch):
    """Веб-поиск цены работы — доп, и задача, к которой он относится, известна."""
    spy = _Spy('{"price": 900, "unit": "м3", "source": "example.ru"}')
    monkeypatch.setattr(price_service, "call_claude", spy)
    sentinel_db = object()

    result = await price_service._web_search_work_price(
        "Кладка стен", task_id="task-2", db=sentinel_db
    )

    assert result is not None and result["min_price"] == 900
    assert spy.calls[0]["is_extra"] is True
    assert spy.calls[0]["task_id"] == "task-2"
    assert spy.calls[0]["db"] is sentinel_db


@pytest.mark.asyncio
async def test_find_material_price_threads_task_through(monkeypatch):
    """Прайс-лист и эмбеддинги бесплатны — task_id доезжает только до веб-поиска."""
    spy = _Spy('{"price": 20, "unit": "шт", "source": "example.ru"}')
    monkeypatch.setattr(price_service, "call_claude", spy)
    monkeypatch.setattr(price_service, "_exact_match_material", lambda name: None)

    async def _no_embedding(name):
        return None

    monkeypatch.setattr(price_service, "_embedding_match_material", _no_embedding)

    price = await price_service.find_material_price(
        "Кирпич керамический", task_id="task-3", db=object()
    )

    assert price == 20
    assert spy.calls[0]["task_id"] == "task-3"
    assert spy.calls[0]["is_extra"] is True


@pytest.mark.asyncio
async def test_main_processing_is_not_extra(monkeypatch):
    """Обработчик задачи по умолчанию пишет вызов как основной, а не как доп."""
    from app.services import claude_service

    logged: list[dict] = []

    async def _fake_log(*args, **kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(claude_service, "_log_api_call", _fake_log)

    class _Usage:
        input_tokens = 10
        output_tokens = 5
        cache_read_input_tokens = 0
        cache_creation_input_tokens = 0
        server_tool_use = None

    class _Block:
        text = "{}"

    class _Response:
        content = [_Block()]
        usage = _Usage()
        stop_reason = "end_turn"

    class _Messages:
        async def create(self, **kwargs):
            return _Response()

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(claude_service, "_get_client", lambda: _Client())

    await claude_service.call_claude(
        messages=[{"role": "user", "content": "привет"}],
        task_id="task-4",
        db=object(),
    )

    assert logged and logged[0]["is_extra"] is False

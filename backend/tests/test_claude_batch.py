"""
Phase 2 — batch-инфраструктура claude_service (Anthropic Message Batches API).

Юнит-тесты с замоканным _client.messages.batches. БД не трогаем (db=None).
План: plans/2026-07-21-estimate-processing-modes.md, Phase 2.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.services.claude_service as cs


@pytest.fixture
def batches(monkeypatch):
    """Заглушка SDK-клиента: cs._get_client() → объект с .messages.batches.

    Клиент создаётся лениво (_get_client, с 25.07 — обход геоблока через
    посредника), поэтому подменяем фабрику, а не модульную переменную _client:
    в тестах она None до первого реального вызова.
    """
    batches_ns = SimpleNamespace()
    client = SimpleNamespace(messages=SimpleNamespace(batches=batches_ns))
    monkeypatch.setattr(cs, "_get_client", lambda: client)
    return batches_ns


# --------------------------------------------------------------------------
# Стоимость batch — уполовиненные тарифы (с точностью до округления 6 знаков)
# --------------------------------------------------------------------------

def test_batch_cost_is_half_of_regular():
    regular = cs._calc_cost("claude-sonnet-4-6", 1000, 500, 200, 300, batch=False)
    batch = cs._calc_cost("claude-sonnet-4-6", 1000, 500, 200, 300, batch=True)
    assert batch < regular
    # batch ≈ regular/2 в пределах округления до 6 знаков
    assert abs(regular - batch * 2) <= Decimal("0.000002")


# --------------------------------------------------------------------------
# Стоимость web search — отдельная от токенов статья ($10 / 1000 поисков)
# --------------------------------------------------------------------------

def test_web_search_adds_flat_fee_on_top_of_tokens():
    no_search = cs._calc_cost("claude-sonnet-4-6", 1000, 500, 200, 300)
    with_search = cs._calc_cost("claude-sonnet-4-6", 1000, 500, 200, 300, web_search_requests=7)
    assert with_search - no_search == Decimal("0.07")


def test_web_search_fee_not_halved_by_batch():
    """Скидка batch — на токены; на поиски её консервативно НЕ применяем."""
    only_search = cs._calc_cost("claude-sonnet-4-6", 0, 0, 0, 0, batch=True, web_search_requests=10)
    assert only_search == Decimal("0.1")


def test_web_search_tool_has_max_uses_cap():
    """Без max_uses поиск бесконтрольный — 22% счёта Anthropic на 28.07.2026."""
    assert cs.WEB_SEARCH_TOOL["max_uses"] >= 1


def test_extract_usage_reads_web_search_requests():
    usage = SimpleNamespace(
        input_tokens=10, output_tokens=20,
        cache_read_input_tokens=30, cache_creation_input_tokens=40,
        server_tool_use=SimpleNamespace(web_search_requests=5),
    )
    assert cs._extract_usage(usage) == (10, 20, 30, 40, 5)


def test_extract_usage_without_server_tool_use():
    """Вызов без web search: поля server_tool_use в usage нет вовсе."""
    usage = SimpleNamespace(
        input_tokens=10, output_tokens=20,
        cache_read_input_tokens=0, cache_creation_input_tokens=0,
    )
    assert cs._extract_usage(usage) == (10, 20, 0, 0, 0)


# --------------------------------------------------------------------------
# Сборка batch-запроса — паритет с call_claude (модель, tools, кэш system)
# --------------------------------------------------------------------------

def test_build_batch_request_shape():
    req = cs.build_batch_request(
        custom_id="chunk-1",
        messages=[{"role": "user", "content": "hi"}],
        system_prompt="SYS",
        use_web_search=True,
        max_tokens=12345,
    )
    assert req["custom_id"] == "chunk-1"
    params = req["params"]
    assert params["model"] == cs.CLAUDE_MODEL
    assert params["max_tokens"] == 12345
    # web search подключён
    assert cs.WEB_SEARCH_TOOL in params["tools"]
    # system закэширован
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["system"][0]["text"] == "SYS"


# --------------------------------------------------------------------------
# submit — возвращает batch_id и прокидывает requests
# --------------------------------------------------------------------------

async def test_submit_claude_batch_returns_id(batches):
    captured = {}

    async def fake_create(*, requests):
        captured["requests"] = requests
        return SimpleNamespace(id="msgbatch_abc123")

    batches.create = fake_create

    reqs = [cs.build_batch_request(custom_id="c1", messages=[{"role": "user", "content": "x"}])]
    batch_id = await cs.submit_claude_batch(reqs)

    assert batch_id == "msgbatch_abc123"
    assert captured["requests"] == reqs


# --------------------------------------------------------------------------
# poll — возвращает processing_status
# --------------------------------------------------------------------------

async def test_poll_claude_batch_status(batches):
    batches.retrieve = AsyncMock(return_value=SimpleNamespace(processing_status="ended"))
    status = await cs.poll_claude_batch("msgbatch_abc123")
    assert status == "ended"


# --------------------------------------------------------------------------
# collect — ключует по custom_id при перемешанном порядке; errored помечается
# --------------------------------------------------------------------------

class _FakeResults:
    """Асинхронно-итерируемая заглушка для .results()."""
    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        async def _gen():
            for it in self._items:
                yield it
        return _gen()


async def test_collect_claude_batch_keys_by_custom_id(batches):
    ok = SimpleNamespace(
        custom_id="c1",
        result=SimpleNamespace(
            type="succeeded",
            message=SimpleNamespace(
                content=[SimpleNamespace(text='{"price": 100}')],
                usage=SimpleNamespace(
                    input_tokens=100,
                    output_tokens=50,
                    cache_read_input_tokens=0,
                    cache_creation_input_tokens=200,
                    server_tool_use=SimpleNamespace(web_search_requests=3),
                ),
            ),
        ),
    )
    errored = SimpleNamespace(custom_id="c2", result=SimpleNamespace(type="errored"))

    # порядок перемешан: errored раньше succeeded
    batches.results = lambda batch_id: _FakeResults([errored, ok])

    out = await cs.collect_claude_batch("msgbatch_abc123")  # db=None → без логирования

    assert set(out.keys()) == {"c1", "c2"}
    assert out["c1"]["text"] == '{"price": 100}'
    assert out["c1"]["error"] is None
    assert out["c2"]["error"] == "errored"
    assert out["c2"]["text"] is None
    assert out["c1"]["usage"]["web_search_requests"] == 3


# --------------------------------------------------------------------------
# Логирование batch-записи идемпотентно: повторный сбор пачки не даёт дубль.
# resume_from_batch вызывается заново после рестарта поллера — без защиты
# метрика завышалась на каждую пересборку.
# --------------------------------------------------------------------------

class _FakeLogSession:
    """Сессия-заглушка: помнит add(), отвечает на SELECT существующей строки."""

    def __init__(self, store: list, existing: bool):
        self._store = store
        self._existing = existing

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        found = 1 if self._existing else None
        return SimpleNamespace(scalar_one_or_none=lambda: found)

    def add(self, obj):
        self._store.append(obj)

    async def commit(self):
        pass


def _patch_log_session(monkeypatch, store: list, existing: bool) -> None:
    import app.database as database

    monkeypatch.setattr(
        database, "AsyncSessionLocal", lambda: _FakeLogSession(store, existing)
    )


async def test_batch_entry_logged_once(monkeypatch):
    saved: list = []
    _patch_log_session(monkeypatch, saved, existing=False)

    await cs._log_api_call(
        "tid-1", db=object(), input_t=100, output_t=50, cache_read_t=0,
        cache_creation_t=0, batch=True, batch_id="msgbatch_1", batch_custom_id="chunk-0",
    )

    assert len(saved) == 1
    assert saved[0].batch_id == "msgbatch_1"
    assert saved[0].batch_custom_id == "chunk-0"


async def test_batch_entry_not_logged_twice(monkeypatch):
    """Строка по (batch_id, custom_id) уже есть → повторную не пишем."""
    saved: list = []
    _patch_log_session(monkeypatch, saved, existing=True)

    await cs._log_api_call(
        "tid-1", db=object(), input_t=100, output_t=50, cache_read_t=0,
        cache_creation_t=0, batch=True, batch_id="msgbatch_1", batch_custom_id="chunk-0",
    )

    assert saved == []


async def test_regular_call_logged_even_if_identical(monkeypatch):
    """Дедупликация — только для batch-записей: обычные вызовы повторяются
    штатно (ретраи, соседние чанки) и каждый стоит денег."""
    saved: list = []
    _patch_log_session(monkeypatch, saved, existing=True)

    await cs._log_api_call(
        "tid-1", db=object(), input_t=100, output_t=50, cache_read_t=0,
        cache_creation_t=0, duration_ms=1234,
    )

    assert len(saved) == 1


# --------------------------------------------------------------------------
# cancel — зовёт SDK с batch_id
# --------------------------------------------------------------------------

async def test_cancel_claude_batch(batches):
    cancel_mock = AsyncMock()
    batches.cancel = cancel_mock
    await cs.cancel_claude_batch("msgbatch_abc123")
    cancel_mock.assert_awaited_once_with("msgbatch_abc123")

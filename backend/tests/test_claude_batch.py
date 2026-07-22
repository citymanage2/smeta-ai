"""
Phase 2 — batch-инфраструктура claude_service (Anthropic Message Batches API).

Юнит-тесты с замоканным _client.messages.batches. БД не трогаем (db=None).
План: plans/2026-07-21-estimate-processing-modes.md, Phase 2.
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import app.services.claude_service as cs


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

async def test_submit_claude_batch_returns_id(monkeypatch):
    captured = {}

    async def fake_create(*, requests):
        captured["requests"] = requests
        return SimpleNamespace(id="msgbatch_abc123")

    monkeypatch.setattr(cs._client.messages.batches, "create", fake_create)

    reqs = [cs.build_batch_request(custom_id="c1", messages=[{"role": "user", "content": "x"}])]
    batch_id = await cs.submit_claude_batch(reqs)

    assert batch_id == "msgbatch_abc123"
    assert captured["requests"] == reqs


# --------------------------------------------------------------------------
# poll — возвращает processing_status
# --------------------------------------------------------------------------

async def test_poll_claude_batch_status(monkeypatch):
    monkeypatch.setattr(
        cs._client.messages.batches,
        "retrieve",
        AsyncMock(return_value=SimpleNamespace(processing_status="ended")),
    )
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


async def test_collect_claude_batch_keys_by_custom_id(monkeypatch):
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
                ),
            ),
        ),
    )
    errored = SimpleNamespace(custom_id="c2", result=SimpleNamespace(type="errored"))

    # порядок перемешан: errored раньше succeeded
    monkeypatch.setattr(
        cs._client.messages.batches,
        "results",
        lambda batch_id: _FakeResults([errored, ok]),
    )

    out = await cs.collect_claude_batch("msgbatch_abc123")  # db=None → без логирования

    assert set(out.keys()) == {"c1", "c2"}
    assert out["c1"]["text"] == '{"price": 100}'
    assert out["c1"]["error"] is None
    assert out["c2"]["error"] == "errored"
    assert out["c2"]["text"] is None


# --------------------------------------------------------------------------
# cancel — зовёт SDK с batch_id
# --------------------------------------------------------------------------

async def test_cancel_claude_batch(monkeypatch):
    cancel_mock = AsyncMock()
    monkeypatch.setattr(cs._client.messages.batches, "cancel", cancel_mock)
    await cs.cancel_claude_batch("msgbatch_abc123")
    cancel_mock.assert_awaited_once_with("msgbatch_abc123")

"""
Забор результатов пачки должен идти через посредника (ANTHROPIC_BASE_URL).

Anthropic отдаёт `results_url` АБСОЛЮТНЫМ (https://api.anthropic.com/...), а SDK
подставляет base_url только относительным путям — из-за этого запрос уходил
напрямую на api.anthropic.com и с РФ-сервера получал 403 forbidden
(«Request not allowed»), роняя batch-режим ESTIMATE_FROM_LIST целиком.

Тест проверяет ФАКТИЧЕСКИ исходящие HTTP-запросы (httpx.MockTransport), а не
внутренности SDK — переживёт апгрейд anthropic и поймает регрессию, если запрос
снова пойдёт мимо посредника.

План: plans/2026-07-29-batch-results-via-proxy.md, Фаза 1.
"""
import json

import httpx
import pytest

import app.services.claude_service as cs

PROXY = "https://proxy.example.com"
BATCH_ID = "msgbatch_test1"
DIRECT_RESULTS_URL = f"https://api.anthropic.com/v1/messages/batches/{BATCH_ID}/results"


def _batch_body(results_url: str = DIRECT_RESULTS_URL) -> dict:
    return {
        "id": BATCH_ID,
        "type": "message_batch",
        "processing_status": "ended",
        "created_at": "2026-07-29T08:59:00Z",
        "expires_at": "2026-08-29T08:59:00Z",
        "ended_at": "2026-07-29T09:01:00Z",
        "archived_at": None,
        "cancel_initiated_at": None,
        "results_url": results_url,
        "request_counts": {
            "processing": 0, "succeeded": 1, "errored": 0, "canceled": 0, "expired": 0,
        },
    }


_JSONL = json.dumps({
    "custom_id": "chunk-0",
    "result": {
        "type": "succeeded",
        "message": {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-6",
            "content": [{"type": "text", "text": '{"items": [{"id": 1, "price": 100}]}'}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 120,
                "output_tokens": 30,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "server_tool_use": {"web_search_requests": 2},
            },
        },
    },
}, ensure_ascii=False) + "\n"


@pytest.fixture
def transport(monkeypatch):
    """Клиент Anthropic поверх MockTransport; собирает URL всех исходящих запросов."""
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path.endswith("/results"):
            return httpx.Response(200, text=_JSONL)
        return httpx.Response(200, json=_batch_body())

    monkeypatch.setattr(cs.settings, "ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cs.settings, "ANTHROPIC_BASE_URL", PROXY)
    monkeypatch.setattr(cs.settings, "ANTHROPIC_PROXY_SECRET", "shhh")
    monkeypatch.setattr(cs, "_http_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(cs, "_client", None)  # ленивый singleton — пересоздать на моках
    return seen


async def test_batch_results_request_goes_through_proxy(transport):
    """Ни один запрос не должен уйти напрямую на api.anthropic.com."""
    await cs.collect_claude_batch(BATCH_ID, task_id=None, db=None)

    assert transport, "SDK не сделал ни одного HTTP-запроса — тест бессмыслен"
    hosts = {url.host for url in transport}
    assert hosts == {"proxy.example.com"}, f"запрос ушёл мимо посредника: {hosts}"
    # именно забор результатов, а не только retrieve
    assert any(str(url).endswith("/results") for url in transport)


async def test_batch_results_parsed_after_rewrite(transport):
    """Переписывание URL не ломает разбор JSONL: текст и usage на месте."""
    out = await cs.collect_claude_batch(BATCH_ID, task_id=None, db=None)

    assert set(out) == {"chunk-0"}
    entry = out["chunk-0"]
    assert entry["error"] is None
    assert json.loads(entry["text"]) == {"items": [{"id": 1, "price": 100}]}
    assert entry["usage"] == {
        "input": 120,
        "output": 30,
        "cache_read": 0,
        "cache_creation": 0,
        "web_search_requests": 2,
    }


async def test_direct_mode_untouched(monkeypatch):
    """Без ANTHROPIC_BASE_URL (локальная разработка) всё идёт на api.anthropic.com."""
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path.endswith("/results"):
            return httpx.Response(200, text=_JSONL)
        return httpx.Response(200, json=_batch_body())

    monkeypatch.setattr(cs.settings, "ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cs.settings, "ANTHROPIC_BASE_URL", "")
    monkeypatch.setattr(cs.settings, "ANTHROPIC_PROXY_SECRET", "")
    monkeypatch.setattr(cs, "_http_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(cs, "_client", None)

    await cs.collect_claude_batch(BATCH_ID, task_id=None, db=None)

    assert {url.host for url in seen} == {"api.anthropic.com"}


async def test_proxy_with_path_prefix_keeps_prefix(monkeypatch):
    """Посредник на подпути (https://host/anthropic) — префикс не теряется."""
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path.endswith("/results"):
            return httpx.Response(200, text=_JSONL)
        return httpx.Response(200, json=_batch_body())

    monkeypatch.setattr(cs.settings, "ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cs.settings, "ANTHROPIC_BASE_URL", f"{PROXY}/anthropic")
    monkeypatch.setattr(cs.settings, "ANTHROPIC_PROXY_SECRET", "shhh")
    monkeypatch.setattr(cs, "_http_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(cs, "_client", None)

    await cs.collect_claude_batch(BATCH_ID, task_id=None, db=None)

    assert str(seen[-1]) == f"{PROXY}/anthropic/v1/messages/batches/{BATCH_ID}/results"


async def test_foreign_host_results_url_left_as_is(monkeypatch):
    """results_url на постороннем хосте не переписываем — переписывать некуда,
    посредник проксирует только API Anthropic."""
    seen: list[httpx.URL] = []
    foreign = "https://storage.example.org/batches/xxx/results"

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path.endswith("/results"):
            return httpx.Response(200, text=_JSONL)
        return httpx.Response(200, json=_batch_body(results_url=foreign))

    monkeypatch.setattr(cs.settings, "ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cs.settings, "ANTHROPIC_BASE_URL", PROXY)
    monkeypatch.setattr(cs.settings, "ANTHROPIC_PROXY_SECRET", "shhh")
    monkeypatch.setattr(cs, "_http_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(cs, "_client", None)

    await cs.collect_claude_batch(BATCH_ID, task_id=None, db=None)

    assert seen[-1].host == "storage.example.org"

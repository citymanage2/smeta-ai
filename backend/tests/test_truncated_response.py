"""Обрезанный ответ (stop_reason=max_tokens) — самый дорогой путь до 28.07.2026.

Было: ValueError бросался ДО логирования, а _call_claude_json_with_retry ретраил
его как временную ошибку — три полных вызова по 32k output (~$1.44), все
оплаченные, все обречённые (промпт не менялся) и ни один не попал в метрику.

Стало: ResponseTruncatedError, usage логируется до падения, ретрая нет,
чанк дробится пополам.

План: plans/2026-07-28-снижение-числа-вызовов-claude.md, Фаза 1.
"""
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.modules.setdefault("fitz", MagicMock())

import app.services.claude_service as cs  # noqa: E402
from app.services.claude_service import ResponseTruncatedError  # noqa: E402
from app.services.task_processor import TaskProcessor  # noqa: E402


def _response(stop_reason: str, output_tokens: int = 32000):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(text='{"items": []}')],
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=output_tokens,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            server_tool_use=SimpleNamespace(web_search_requests=4),
        ),
    )


def _patch_client(monkeypatch, response) -> dict:
    """Клиент-заглушка; возвращает счётчик обращений к messages.create."""
    calls = {"n": 0}

    async def fake_create(**kwargs):
        calls["n"] += 1
        return response

    client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(cs, "_get_client", lambda: client)
    return calls


async def test_truncated_response_raises_typed_error(monkeypatch):
    _patch_client(monkeypatch, _response("max_tokens"))

    with pytest.raises(ResponseTruncatedError):
        await cs.call_claude([{"role": "user", "content": "x"}])


async def test_truncated_response_is_still_logged(monkeypatch):
    """Оборванный ответ оплачен — токены должны попасть в метрику."""
    _patch_client(monkeypatch, _response("max_tokens"))
    logged: list = []

    async def fake_log(*args, **kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(cs, "_log_api_call", fake_log)

    with pytest.raises(ResponseTruncatedError):
        await cs.call_claude([{"role": "user", "content": "x"}], task_id="t1", db=object())

    assert len(logged) == 1, "оплаченный обрезанный вызов не залогирован"
    assert logged[0]["web_search_requests"] == 4


async def test_truncated_response_not_retried_by_chunk_retry(monkeypatch):
    """Ретрай тем же промптом снова упрётся в потолок — повторов быть не должно."""
    calls = _patch_client(monkeypatch, _response("max_tokens"))
    p = TaskProcessor("tid-trunc", db=MagicMock())

    with pytest.raises(ResponseTruncatedError):
        await p._call_claude_json_with_retry(
            [{"role": "user", "content": "x"}],
            system_prompt="SYS",
            chunk_retry_delays=(0.0, 0.0, 0.0),
        )

    assert calls["n"] == 1, f"ожидался один вызов, сделано {calls['n']}"


async def test_normal_response_still_returns_text(monkeypatch):
    """Обычный ответ (end_turn) не задет правкой."""
    _patch_client(monkeypatch, _response("end_turn", output_tokens=100))
    result = await cs.call_claude([{"role": "user", "content": "x"}])
    assert result == '{"items": []}'


# --------------------------------------------------------------------------
# Дробление порции пополам — проверяем на fix_empty_prices, где весь путь
# (сбор батчей → вызов → применение) выполняется целиком.
# --------------------------------------------------------------------------

async def test_truncated_batch_is_split_in_half_and_priced():
    """Батч из 5 позиций не влез в ответ → две половины, все цены проставлены."""
    import re

    items = [
        {"type": "Работа", "name": f"Работа {i}", "unit": "м3", "quantity": 1}
        for i in range(5)
    ]
    task = MagicMock()
    task.progress_data = {"items": items}
    task.processing_mode = "fast"
    result = MagicMock()
    result.scalar_one_or_none.return_value = task
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    p = TaskProcessor("tid-split", db=db)
    p.update_progress = AsyncMock()
    p._check_cancelled = AsyncMock()

    calls = {"n": 0, "sizes": []}

    async def fake_claude(messages, **kwargs):
        calls["n"] += 1
        ids = [int(x) for x in re.findall(r'"id":\s*(\d+)', messages[0]["content"])]
        calls["sizes"].append(len(ids))
        if calls["n"] == 1:
            raise ResponseTruncatedError("too big")
        return {"items": [{"id": i, "work_price": 100 + i} for i in ids]}

    p._call_claude_json_with_retry = fake_claude

    await p.fix_empty_prices()

    # Один обрезанный вызов на 5 позиций → две половины вместо трёх повторов.
    assert calls["sizes"] == [5, 2, 3], calls["sizes"]
    assert [it.get("work_price") for it in items] == [100, 101, 102, 103, 104]

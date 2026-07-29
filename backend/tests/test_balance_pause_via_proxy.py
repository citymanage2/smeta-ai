"""
Распознавание «баланс исчерпан», когда агрегатор прячет его за 429/5xx.

Пробел, из-за которого задача простояла 167 минут в «Обработке» вместо паузы:
`_raise_if_insufficient_balance` вызывался ТОЛЬКО в ветке APIStatusError со
status_code < 500. Мимо проходили:

- 429 RateLimitError — перехватывается ВЫШЕ отдельным except → бэкофф до 900 с
  на попытку, 4 попытки, умножить на число чанков = часы;
- 5xx APIStatusError — уходит в retry по той же причине.

Прямой Anthropic отдаёт 400 с "credit balance", но на проде запросы идут через
агрегатор (ANTHROPIC_BASE_URL), который вправе ответить своим кодом. Тогда
пустой счёт выглядел как временный сбой, и вместо мгновенной паузы включался
многочасовой автоповтор.

Ожидаемое поведение: балансовая ошибка под ЛЮБЫМ кодом → InsufficientBalanceError
сразу, без единого ретрая (ретраи не вернут деньги на счёт).

План: plans/2026-07-29-diagnostika-v-admin-panel.md, Фаза 4.
"""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx
import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.services.claude_service import (  # noqa: E402
    call_claude,
    InsufficientBalanceError,
)


def _rate_limit_error(message: str) -> anthropic.RateLimitError:
    """429 с произвольным текстом в body.error.message."""
    body = {"error": {"type": "rate_limit_error", "message": message}}
    raw = httpx.Response(
        status_code=429,
        headers={},
        content=b"{}",
        request=httpx.Request("POST", "https://proxy.example/v1/messages"),
    )
    return anthropic.RateLimitError(message, response=raw, body=body)


def _server_error(status_code: int, message: str) -> anthropic.APIStatusError:
    """5xx с произвольным текстом в body.error.message."""
    body = {"error": {"type": "api_error", "message": message}}
    raw = httpx.Response(
        status_code=status_code,
        headers={},
        content=b"{}",
        request=httpx.Request("POST", "https://proxy.example/v1/messages"),
    )
    return anthropic.APIStatusError(message, response=raw, body=body)


@pytest.mark.asyncio
async def test_429_with_balance_marker_pauses_immediately():
    """429 с текстом про баланс → InsufficientBalanceError, без sleep и ретраев."""
    err = _rate_limit_error("Your credit balance is too low to access the API")
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=err)

    with patch("app.services.claude_service._get_client", return_value=client), \
         patch("app.services.claude_service.asyncio.sleep", new=AsyncMock()) as slept:
        with pytest.raises(InsufficientBalanceError):
            await call_claude([{"role": "user", "content": "hi"}])

    # Ровно одна попытка: ретраить нехватку денег бессмысленно и дорого по времени.
    assert client.messages.create.await_count == 1
    slept.assert_not_awaited()


@pytest.mark.asyncio
async def test_429_without_balance_marker_still_retries():
    """Обычный rate limit не должен уезжать в паузу — только ретраи."""
    err = _rate_limit_error("Number of requests has exceeded your rate limit")
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=err)

    with patch("app.services.claude_service._get_client", return_value=client), \
         patch("app.services.claude_service.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(anthropic.RateLimitError):
            await call_claude([{"role": "user", "content": "hi"}])

    assert client.messages.create.await_count > 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 502, 503])
async def test_5xx_with_balance_marker_pauses_immediately(status_code):
    """5xx от агрегатора с балансовым текстом → пауза, а не многочасовой ретрай."""
    err = _server_error(status_code, "insufficient balance on account")
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=err)

    with patch("app.services.claude_service._get_client", return_value=client), \
         patch("app.services.claude_service.asyncio.sleep", new=AsyncMock()) as slept:
        with pytest.raises(InsufficientBalanceError):
            await call_claude([{"role": "user", "content": "hi"}])

    assert client.messages.create.await_count == 1
    slept.assert_not_awaited()


@pytest.mark.asyncio
async def test_5xx_without_balance_marker_still_retries():
    """Настоящий сбой сервера остаётся ретраибельным."""
    err = _server_error(503, "upstream temporarily unavailable")
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=err)

    with patch("app.services.claude_service._get_client", return_value=client), \
         patch("app.services.claude_service.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(anthropic.APIStatusError):
            await call_claude([{"role": "user", "content": "hi"}])

    assert client.messages.create.await_count > 1

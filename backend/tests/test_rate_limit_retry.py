"""TDD tests for 429 Rate Limit retry behaviour in call_claude.

Required behaviour:
- When the API returns RateLimitError, call_claude retries.
- If the response includes a 'retry-after' header, that many seconds are waited
  before the next attempt (not the hardcoded delay).
- If 'retry-after' is absent, a sensible default (60 s) is used.
- On the attempt after the wait the call succeeds and its result is returned.
- After all retries are exhausted the original RateLimitError is re-raised.
"""
import asyncio
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import httpx
import pytest
import anthropic

from app.services.claude_service import call_claude


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rate_limit_error(retry_after: Optional[float] = None) -> anthropic.RateLimitError:
    """Build a fake RateLimitError, optionally carrying a retry-after header."""
    headers: dict[str, str] = {"x-request-id": "test-req"}
    if retry_after is not None:
        headers["retry-after"] = str(retry_after)

    raw_response = httpx.Response(
        status_code=429,
        headers=headers,
        content=b'{"error": {"type": "rate_limit_error", "message": "Rate limit exceeded"}}',
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    return anthropic.RateLimitError(
        message="Rate limit exceeded",
        response=raw_response,
        body={"error": {"type": "rate_limit_error", "message": "Rate limit exceeded"}},
    )


def _make_success_response(text: str = "ok") -> MagicMock:
    block = MagicMock()
    block.text = text
    block.stop_reason = None
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    return response


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_rate_limit_is_retried(monkeypatch):
    """call_claude retries at least once after a RateLimitError."""
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_rate_limit_error(retry_after=0.01)
        return _make_success_response()

    monkeypatch.setattr("app.services.claude_service._client.messages.create", fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", AsyncMock())

    result = await call_claude([{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert call_count == 2


async def test_retry_after_header_is_used_as_sleep_duration(monkeypatch):
    """When retry-after header is present, asyncio.sleep is called with that value."""
    sleep_mock = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_rate_limit_error(retry_after=42)
        return _make_success_response()

    monkeypatch.setattr("app.services.claude_service._client.messages.create", fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", sleep_mock)

    await call_claude([{"role": "user", "content": "hi"}])

    # The sleep call for the rate-limit wait must use the header value
    sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
    assert any(abs(s - 42) < 1 for s in sleep_calls), (
        f"Expected sleep ~42 s from retry-after header, got: {sleep_calls}"
    )


async def test_default_sleep_used_when_no_retry_after_header(monkeypatch):
    """When retry-after header is absent, sleep for DEFAULT_RATE_LIMIT_DELAY seconds."""
    from app.services.claude_service import DEFAULT_RATE_LIMIT_DELAY

    sleep_mock = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_rate_limit_error(retry_after=None)  # no header
        return _make_success_response()

    monkeypatch.setattr("app.services.claude_service._client.messages.create", fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", sleep_mock)

    await call_claude([{"role": "user", "content": "hi"}])

    sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
    assert any(abs(s - DEFAULT_RATE_LIMIT_DELAY) < 1 for s in sleep_calls), (
        f"Expected sleep ~{DEFAULT_RATE_LIMIT_DELAY} s (default), got: {sleep_calls}"
    )


async def test_rate_limit_exhausted_raises(monkeypatch):
    """After all retries are exhausted, the RateLimitError is re-raised."""
    async def always_rate_limit(**kwargs):
        raise _make_rate_limit_error(retry_after=0.01)

    monkeypatch.setattr("app.services.claude_service._client.messages.create", always_rate_limit)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", AsyncMock())

    with pytest.raises(anthropic.RateLimitError):
        await call_claude([{"role": "user", "content": "hi"}])


async def test_rate_limit_warning_is_logged(monkeypatch, capsys):
    """A warning is logged when a rate limit is hit."""
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_rate_limit_error(retry_after=0.01)
        return _make_success_response()

    monkeypatch.setattr("app.services.claude_service._client.messages.create", fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", AsyncMock())

    await call_claude([{"role": "user", "content": "hi"}])

    output = capsys.readouterr().out
    assert "rate limit" in output.lower() or "429" in output, (
        f"Expected rate-limit warning in stdout, got: {output[:500]}"
    )

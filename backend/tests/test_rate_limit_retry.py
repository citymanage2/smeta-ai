"""TDD tests for 429 Rate Limit retry behaviour in call_claude.

Required behaviour:
- When the API returns RateLimitError, call_claude retries.
- If the response includes a 'retry-after' header AND it exceeds the backoff
  minimum for this attempt, that many seconds are waited.
- Exponential backoff minimums: 1st 429 → 60 s, 2nd → 120 s, 3rd → 240 s, cap 900 s.
- 'processing_timeout' wraps ONLY _client.messages.create, not the rate-limit sleep.
- Rate-limit sleep therefore does NOT consume the processing_timeout budget.
- After all retries are exhausted the original RateLimitError is re-raised.
"""
import asyncio
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

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
# Basic retry tests (pre-existing behaviour)
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


async def test_default_sleep_used_when_no_retry_after_header(monkeypatch):
    """When retry-after header is absent, sleep for at least DEFAULT_RATE_LIMIT_DELAY seconds."""
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
    assert any(s >= DEFAULT_RATE_LIMIT_DELAY for s in sleep_calls), (
        f"Expected sleep >= {DEFAULT_RATE_LIMIT_DELAY} s (default), got: {sleep_calls}"
    )


# ---------------------------------------------------------------------------
# Change 4: Exponential backoff tests
# ---------------------------------------------------------------------------

async def test_retry_after_above_minimum_uses_header_value(monkeypatch):
    """When retry-after > backoff minimum (60 s), the API header value is used."""
    sleep_mock = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_rate_limit_error(retry_after=300)  # well above 60 s minimum
        return _make_success_response()

    monkeypatch.setattr("app.services.claude_service._client.messages.create", fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", sleep_mock)

    await call_claude([{"role": "user", "content": "hi"}])

    sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
    assert any(abs(s - 300) < 1 for s in sleep_calls), (
        f"Expected sleep ~300 s from retry-after header, got: {sleep_calls}"
    )


async def test_backoff_minimum_60s_for_first_429(monkeypatch):
    """First 429: sleep at least 60 s even if retry-after is smaller."""
    sleep_mock = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_rate_limit_error(retry_after=5)  # below 60 s minimum
        return _make_success_response()

    monkeypatch.setattr("app.services.claude_service._client.messages.create", fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", sleep_mock)

    await call_claude([{"role": "user", "content": "hi"}])

    sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
    assert any(s >= 60 for s in sleep_calls), (
        f"Expected at least one sleep >= 60 s for first 429, got: {sleep_calls}"
    )


async def test_exponential_backoff_increases_per_consecutive_429(monkeypatch):
    """Backoff minimum escalates: 1st 429 >= 60 s, 2nd >= 120 s, 3rd >= 240 s."""
    sleep_mock = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise _make_rate_limit_error(retry_after=1)  # always below minimums
        return _make_success_response()

    monkeypatch.setattr("app.services.claude_service._client.messages.create", fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", sleep_mock)

    await call_claude([{"role": "user", "content": "hi"}])

    sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
    assert len(sleep_calls) >= 3, f"Expected >= 3 sleep calls, got: {sleep_calls}"
    assert sleep_calls[0] >= 60, f"1st 429 should wait >= 60 s, got {sleep_calls[0]}"
    assert sleep_calls[1] >= 120, f"2nd 429 should wait >= 120 s, got {sleep_calls[1]}"
    assert sleep_calls[2] >= 240, f"3rd 429 should wait >= 240 s, got {sleep_calls[2]}"


async def test_backoff_capped_at_900s(monkeypatch):
    """Backoff is capped at 900 s even if retry-after is larger."""
    sleep_mock = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_rate_limit_error(retry_after=9999)  # absurdly large
        return _make_success_response()

    monkeypatch.setattr("app.services.claude_service._client.messages.create", fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", sleep_mock)

    await call_claude([{"role": "user", "content": "hi"}])

    sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
    assert all(s <= 900 for s in sleep_calls), (
        f"Backoff should be capped at 900 s, got: {sleep_calls}"
    )


async def test_rate_limit_log_includes_retry_after_and_actual_wait(monkeypatch, capsys):
    """Log entry includes both the API retry-after value and the actual wait used."""
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_rate_limit_error(retry_after=839)
        return _make_success_response()

    monkeypatch.setattr("app.services.claude_service._client.messages.create", fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", AsyncMock())

    await call_claude([{"role": "user", "content": "hi"}])

    output = capsys.readouterr().out
    # The log should mention the retry-after value
    assert "839" in output, f"Expected retry-after value 839 in log: {output[:500]}"


# ---------------------------------------------------------------------------
# Changes 1 & 2: processing_timeout tests
# ---------------------------------------------------------------------------

async def test_slow_api_call_triggers_processing_timeout(monkeypatch):
    """When the API call itself takes longer than processing_timeout, TimeoutError is raised."""
    async def slow_create(**kwargs):
        await asyncio.sleep(10)  # real sleep inside the API call — causes timeout
        return _make_success_response()

    monkeypatch.setattr("app.services.claude_service._client.messages.create", slow_create)
    # NOT patching asyncio.sleep globally — the sleep inside slow_create is real

    with pytest.raises(asyncio.TimeoutError):
        await call_claude(
            [{"role": "user", "content": "hi"}],
            processing_timeout=0.05,  # 50 ms — well below the 10 s API sleep
        )


async def test_rate_limit_sleep_not_counted_against_processing_timeout(monkeypatch):
    """Rate-limit sleep is outside the processing_timeout wrapper and does not consume it."""
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_rate_limit_error(retry_after=0.01)
        return _make_success_response()

    # Make the rate-limit sleep instant so the test is fast
    monkeypatch.setattr("app.services.claude_service._client.messages.create", fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", AsyncMock())

    # With processing_timeout=0.001 (1 ms), a rate-limit sleep of any duration
    # must NOT cause TimeoutError because it is outside wait_for.
    result = await call_claude(
        [{"role": "user", "content": "hi"}],
        processing_timeout=0.001,
    )
    assert result == "ok"
    assert call_count == 2

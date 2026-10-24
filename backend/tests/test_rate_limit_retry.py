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
from unittest.mock import AsyncMock

import pytest

from app.services.claude_service import call_claude
from tests.helpers.anthropic_api import claude_message, rate_limit_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Basic retry tests (pre-existing behaviour)
# ---------------------------------------------------------------------------

async def test_rate_limit_is_retried(monkeypatch, patch_claude_create):
    """call_claude retries at least once after a RateLimitError."""
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise rate_limit_error(retry_after=0.01)
        return claude_message("ok")

    patch_claude_create(fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", AsyncMock())

    result = await call_claude([{"role": "user", "content": "hi"}])
    assert result == "ok"
    assert call_count == 2


async def test_default_sleep_used_when_no_retry_after_header(monkeypatch, patch_claude_create):
    """When retry-after header is absent, sleep for at least DEFAULT_RATE_LIMIT_DELAY seconds."""
    from app.services.claude_service import DEFAULT_RATE_LIMIT_DELAY

    sleep_mock = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise rate_limit_error(retry_after=None)  # no header
        return claude_message("ok")

    patch_claude_create(fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", sleep_mock)

    await call_claude([{"role": "user", "content": "hi"}])

    sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
    assert any(s >= DEFAULT_RATE_LIMIT_DELAY for s in sleep_calls), (
        f"Expected sleep >= {DEFAULT_RATE_LIMIT_DELAY} s (default), got: {sleep_calls}"
    )


# ---------------------------------------------------------------------------
# Change 4: Exponential backoff tests
# ---------------------------------------------------------------------------

async def test_retry_after_above_minimum_uses_header_value(monkeypatch, patch_claude_create):
    """When retry-after > backoff minimum (60 s), the API header value is used."""
    sleep_mock = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise rate_limit_error(retry_after=300)  # well above 60 s minimum
        return claude_message("ok")

    patch_claude_create(fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", sleep_mock)

    await call_claude([{"role": "user", "content": "hi"}])

    sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
    assert any(abs(s - 300) < 1 for s in sleep_calls), (
        f"Expected sleep ~300 s from retry-after header, got: {sleep_calls}"
    )


async def test_backoff_minimum_60s_for_first_429(monkeypatch, patch_claude_create):
    """First 429: sleep at least 60 s even if retry-after is smaller."""
    sleep_mock = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise rate_limit_error(retry_after=5)  # below 60 s minimum
        return claude_message("ok")

    patch_claude_create(fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", sleep_mock)

    await call_claude([{"role": "user", "content": "hi"}])

    sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
    assert any(s >= 60 for s in sleep_calls), (
        f"Expected at least one sleep >= 60 s for first 429, got: {sleep_calls}"
    )


async def test_exponential_backoff_increases_per_consecutive_429(monkeypatch, patch_claude_create):
    """Backoff minimum escalates: 1st 429 >= 60 s, 2nd >= 120 s, 3rd >= 240 s."""
    sleep_mock = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise rate_limit_error(retry_after=1)  # always below minimums
        return claude_message("ok")

    patch_claude_create(fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", sleep_mock)

    await call_claude([{"role": "user", "content": "hi"}])

    sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
    assert len(sleep_calls) >= 3, f"Expected >= 3 sleep calls, got: {sleep_calls}"
    assert sleep_calls[0] >= 60, f"1st 429 should wait >= 60 s, got {sleep_calls[0]}"
    assert sleep_calls[1] >= 120, f"2nd 429 should wait >= 120 s, got {sleep_calls[1]}"
    assert sleep_calls[2] >= 240, f"3rd 429 should wait >= 240 s, got {sleep_calls[2]}"


async def test_backoff_capped_at_900s(monkeypatch, patch_claude_create):
    """Backoff is capped at 900 s even if retry-after is larger."""
    sleep_mock = AsyncMock()
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise rate_limit_error(retry_after=9999)  # absurdly large
        return claude_message("ok")

    patch_claude_create(fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", sleep_mock)

    await call_claude([{"role": "user", "content": "hi"}])

    sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
    assert all(s <= 900 for s in sleep_calls), (
        f"Backoff should be capped at 900 s, got: {sleep_calls}"
    )


# ---------------------------------------------------------------------------
# Changes 1 & 2: processing_timeout tests
# ---------------------------------------------------------------------------

async def test_slow_api_call_triggers_processing_timeout(monkeypatch, patch_claude_create):
    """When the API call itself takes longer than processing_timeout, TimeoutError is raised."""
    async def slow_create(**kwargs):
        await asyncio.sleep(10)  # real sleep inside the API call — causes timeout
        return claude_message("ok")

    patch_claude_create(slow_create)
    # NOT patching asyncio.sleep globally — the sleep inside slow_create is real

    with pytest.raises(asyncio.TimeoutError):
        await call_claude(
            [{"role": "user", "content": "hi"}],
            processing_timeout=0.05,  # 50 ms — well below the 10 s API sleep
        )


async def test_rate_limit_sleep_counted_in_cumulative_timeout(monkeypatch, patch_claude_create):
    """Rate-limit sleep вычитается из cumulative processing_timeout.

    При замоканном sleep (= мгновенный, elapsed ≈ 0) и достаточном бюджете
    второй attempt проходит успешно — оставшийся бюджет почти равен исходному.
    """
    call_count = 0

    async def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise rate_limit_error(retry_after=0.01)
        return claude_message("ok")

    # Мокаем sleep — мгновенный, elapsed остаётся близким к 0
    patch_claude_create(fake_create)
    monkeypatch.setattr("app.services.claude_service.asyncio.sleep", AsyncMock())

    # При большом бюджете (30 с) и мгновенном sleep — second attempt успешен
    result = await call_claude(
        [{"role": "user", "content": "hi"}],
        processing_timeout=30.0,
    )
    assert result == "ok"
    assert call_count == 2

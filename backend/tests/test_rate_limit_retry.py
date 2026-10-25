"""TDD tests for 429 Rate Limit retry behaviour in call_claude.

Required behaviour:
- When the API returns RateLimitError, call_claude retries.
- If the response includes a 'retry-after' header AND it exceeds the backoff
  minimum for this attempt, that many seconds are waited.
- Exponential backoff minimums: 1st 429 → 60 s, 2nd → 120 s, 3rd → 240 s, cap 900 s.
- 'processing_timeout' — общий бюджет вызова: сон после 429 тоже его расходует,
  и попытка, на которую бюджета не осталось, не отправляется.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.models.system_event import SystemEvent
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


@pytest_asyncio.fixture
async def rate_limit_events(db_session, app_sessions):
    """Каждый 429 пишет строку в `system_events` своей сессией: она идёт в
    тестовую БД, а не мимо неё, и после теста убирается."""
    yield
    await db_session.execute(delete(SystemEvent))
    await db_session.commit()


@pytest.mark.parametrize("retry_after, sleeps", [
    pytest.param([None], [60], id="no-header-default-60"),
    pytest.param([5], [60], id="below-minimum-waits-60"),
    pytest.param([300], [300], id="header-above-minimum"),
    pytest.param([1, 1, 1], [60, 120, 240], id="backoff-doubles-per-429"),
    pytest.param([9999], [900], id="capped-at-900"),
])
async def test_rate_limit_wait(claude_api, api_sleeps, rate_limit_events, retry_after, sleeps):
    """Ожидание после 429: заголовок retry-after, но не меньше ступени бэкоффа
    (60 → 120 → 240 с на каждый подряд идущий 429) и не больше 900 с."""
    ai = claude_api(*[rate_limit_error(retry_after=r) for r in retry_after], claude_message("ok"))

    assert await call_claude([{"role": "user", "content": "hi"}]) == "ok"

    assert api_sleeps == sleeps
    assert len(ai.calls) == len(retry_after) + 1


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


async def test_rate_limit_sleep_counted_in_cumulative_timeout(
    monkeypatch, claude_api, rate_limit_events
):
    """Сон после 429 съедает бюджет processing_timeout: проспали больше бюджета —
    TimeoutError, второго запроса к API нет."""
    from app.services import claude_service

    class _SleepsTenthOfSecond:
        """`asyncio` для claude_service: любая пауза длится 0,1 с по-настоящему."""

        def __getattr__(self, name):
            return getattr(asyncio, name)

        async def sleep(self, delay, result=None):
            await asyncio.sleep(0.1)
            return result

    monkeypatch.setattr(claude_service, "asyncio", _SleepsTenthOfSecond())
    ai = claude_api(rate_limit_error(retry_after=1))

    with pytest.raises(asyncio.TimeoutError):
        await call_claude(
            [{"role": "user", "content": "hi"}],
            processing_timeout=0.05,
        )

    assert len(ai.calls) == 1

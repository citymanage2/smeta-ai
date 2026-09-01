"""Фоновая сверка трат не долбится в отказ по правам.

01.09.2026 отчёт ответил `403 permission_error`: организация в Console личная, а
Admin API для таких недоступен — это не сбой, а её постоянное свойство. Часовой
job в таком режиме писал бы в лог по отказу каждый час до скончания веков, и
среди этого мусора потерялась бы настоящая поломка.

Сетевые сбои и 5xx паузу не вызывают: они проходят сами, и ретрай через час для
них правильный.

План: plans/2026-09-01-ostatok-deneg-na-api.md, Фаза 6.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app import worker
from app.services.anthropic_admin import AdminApiError


@pytest.fixture(autouse=True)
def _reset_pause():
    worker._cost_sync_paused_until = None
    yield
    worker._cost_sync_paused_until = None


class TestHardRefusal:
    @pytest.mark.asyncio
    async def test_403_pauses_for_a_day(self):
        sync = AsyncMock(side_effect=AdminApiError("Отчёт о тратах: HTTP 403 permission_error"))
        with patch("app.services.balance_service.sync_cost_days", sync), patch(
            "app.services.anthropic_admin.is_configured", lambda: True
        ):
            await worker._sync_api_cost_job()
            assert worker._cost_sync_paused_until is not None
            # Следующий тик в пределах суток даже не ходит в Anthropic.
            await worker._sync_api_cost_job()

        assert sync.await_count == 1

    @pytest.mark.asyncio
    async def test_401_pauses_too(self):
        sync = AsyncMock(side_effect=AdminApiError("Отчёт о тратах: HTTP 401 authentication_error"))
        with patch("app.services.balance_service.sync_cost_days", sync), patch(
            "app.services.anthropic_admin.is_configured", lambda: True
        ):
            await worker._sync_api_cost_job()

        assert worker._cost_sync_paused_until is not None

    @pytest.mark.asyncio
    async def test_pause_expires(self):
        sync = AsyncMock(side_effect=AdminApiError("Отчёт о тратах: HTTP 403 permission_error"))
        with patch("app.services.balance_service.sync_cost_days", sync), patch(
            "app.services.anthropic_admin.is_configured", lambda: True
        ):
            await worker._sync_api_cost_job()
            # Сутки прошли — пробуем снова: права могли выдать.
            worker._cost_sync_paused_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            await worker._sync_api_cost_job()

        assert sync.await_count == 2


class TestSoftFailure:
    @pytest.mark.asyncio
    async def test_network_error_does_not_pause(self):
        """Обрыв связи пройдёт сам — ретраить через час правильно."""
        sync = AsyncMock(side_effect=AdminApiError("Отчёт о тратах недоступен: ConnectTimeout"))
        with patch("app.services.balance_service.sync_cost_days", sync), patch(
            "app.services.anthropic_admin.is_configured", lambda: True
        ):
            await worker._sync_api_cost_job()
            await worker._sync_api_cost_job()

        assert worker._cost_sync_paused_until is None
        assert sync.await_count == 2

    @pytest.mark.asyncio
    async def test_success_clears_pause(self):
        worker._cost_sync_paused_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        sync = AsyncMock(return_value=3)
        with patch("app.services.balance_service.sync_cost_days", sync), patch(
            "app.services.anthropic_admin.is_configured", lambda: True
        ):
            await worker._sync_api_cost_job()

        assert worker._cost_sync_paused_until is None


class TestNoKey:
    @pytest.mark.asyncio
    async def test_without_key_no_request_at_all(self):
        sync = AsyncMock()
        with patch("app.services.balance_service.sync_cost_days", sync), patch(
            "app.services.anthropic_admin.is_configured", lambda: False
        ):
            await worker._sync_api_cost_job()

        sync.assert_not_awaited()

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

import httpx
import pytest

from app import worker
from app.services import anthropic_admin
from app.services.anthropic_admin import AdminApiError


@pytest.fixture(autouse=True)
def _reset_pause():
    worker._cost_sync_paused_until = None
    yield
    worker._cost_sync_paused_until = None


class _CostReport:
    """Anthropic `cost_report` по HTTP: отвечает заданным статусом, считает запросы.

    Подменён только транспорт httpx — запрос строит и разбирает настоящий клиент
    `anthropic_admin`, поэтому воркер видит ровно тот текст ошибки, что в проде.
    """

    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body
        self.requests: list = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body)


@pytest.fixture
def cost_report(monkeypatch, app_sessions):
    from app.config import settings

    def _install(status: int, body: dict) -> _CostReport:
        report = _CostReport(status, body)
        transport = httpx.MockTransport(report.handler)
        real_client = httpx.AsyncClient

        class _Httpx:
            def __getattr__(self, name):
                return getattr(httpx, name)

            @staticmethod
            def AsyncClient(**kwargs):
                return real_client(transport=transport, **kwargs)

        monkeypatch.setattr(anthropic_admin, "httpx", _Httpx())
        monkeypatch.setattr(settings, "ANTHROPIC_ADMIN_KEY", "sk-ant-admin01-test")
        return report

    return _install


class TestHardRefusal:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status, error_type", [
        (403, "permission_error"),     # организация личная — Admin API недоступен
        (401, "authentication_error"),  # ключ не принят
    ])
    async def test_refusal_pauses_for_a_day(self, cost_report, status, error_type):
        """Отказ по правам — свойство организации, а не сбой: следующий тик в
        пределах суток в Anthropic даже не ходит."""
        report = cost_report(
            status, {"type": "error", "error": {"type": error_type, "message": "denied"}}
        )

        await worker._sync_api_cost_job()
        await worker._sync_api_cost_job()

        assert len(report.requests) == 1

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


class TestNoKey:
    @pytest.mark.asyncio
    async def test_without_key_no_request_at_all(self):
        sync = AsyncMock()
        with patch("app.services.balance_service.sync_cost_days", sync), patch(
            "app.services.anthropic_admin.is_configured", lambda: False
        ):
            await worker._sync_api_cost_job()

        sync.assert_not_awaited()
